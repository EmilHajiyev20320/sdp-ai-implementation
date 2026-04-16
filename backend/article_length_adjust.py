"""
Bring generated English body into a word-count window without failing the pipeline.

LLMs often miss exact length despite instructions (no internal counter, greedy stopping,
conflicting goals like "Sources" block, temperature). We fix deterministically + retries.
"""
import re

try:
    from backend.article_validator import word_count
    from backend.text_writer import write_english_article
except ImportError:
    from article_validator import word_count
    from text_writer import write_english_article


def _split_body_and_sources(body_en: str) -> tuple[str, str]:
    """Same rules as main.split_body_and_sources (avoid circular imports)."""
    body = body_en.strip()
    match = re.search(r"\n\s*Sources:?\s*\n", body, re.IGNORECASE)
    if match:
        idx = match.start()
        return body[:idx].strip(), body[idx:].strip()
    lines = body.split("\n")
    sources_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("http://") or stripped.startswith("https://"):
            sources_start = i
            break
        if re.match(r"^\*\s*https?://", stripped):
            sources_start = i
            break
    if sources_start >= 0:
        return "\n".join(lines[:sources_start]).strip(), "\n".join(lines[sources_start:]).strip()
    return body, ""


def _sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def trim_english_to_max_words(body_en: str, max_words: int) -> str:
    """Shorten article part to fit total word count <= max_words; keep Sources block intact."""
    article, sources = _split_body_and_sources(body_en)
    src_wc = word_count(sources)
    budget = max(1, max_words - src_wc - 2)
    if word_count(article) <= budget:
        return (article + ("\n\n" + sources if sources else "")).strip()

    sents = _sentences(article.replace("\n\n", " \n\n "))
    built: list[str] = []
    wc = 0
    for s in sents:
        sw = word_count(s)
        if wc + sw <= budget:
            built.append(s)
            wc += sw
        elif wc == 0:
            words = s.split()
            if len(words) > budget:
                built.append(" ".join(words[:budget]).rstrip(",;:") + "...")
            else:
                built.append(s)
            break
        else:
            break
    main = "\n\n".join(built) if built else article
    if word_count(main) > budget:
        words = main.split()
        main = " ".join(words[:budget]).rstrip(",;:") + ("..." if len(words) > budget else "")
    out = main
    if sources:
        out = out + "\n\n" + sources
    return out.strip()


def _expand_prompt(body: str, wc: int, lo: int, hi: int) -> str:
    return f"""You are editing a news article. The draft below is {wc} words but must be {lo}–{hi} words total.

Rules:
- Keep the same factual claims and do not invent new facts.
- Keep the same Sources section at the end (same URLs); you may fix formatting only.
- Add substantive paragraphs (context, implications, clearer explanations) until length is in range.
- Output ONLY the full revised article, {lo}–{hi} words.
- The article must remain in English only. Do not include Azerbaijani letters or Azerbaijani words.

DRAFT:
{body.strip()}
""".strip()


def stretch_with_source_excerpts(body: str, sources: list[dict], min_words: int) -> str:
    """Last resort: append text from source snippets until min_words (no invented facts)."""
    if word_count(body) >= min_words or not sources:
        return body
    body_out = body.rstrip() + "\n\nFurther context from the supplied sources:\n\n"
    wc = word_count(body_out)
    for s in sources:
        if wc >= min_words:
            break
        snip = (s.get("snippet") or "").strip()
        if not snip:
            continue
        snip = re.sub(r"\s+", " ", snip)
        para = snip + "\n\n"
        body_out += para
        wc = word_count(body_out)
    return body_out.strip()


def fit_english_body_to_word_range(
    body_en: str,
    sources: list[dict],
    min_words: int,
    max_words: int,
    max_expand_attempts: int = 4,
) -> tuple[str, dict]:
    """
    Trim if too long; if too short, ask the model to expand (retries), then source excerpts.

    Returns:
        (adjusted_body, meta) with keys: initial_wc, final_wc, trimmed, expand_attempts, stretched.
    """
    meta: dict = {
        "initial_wc": word_count(body_en),
        "final_wc": 0,
        "trimmed": False,
        "expand_attempts": 0,
        "stretched_from_sources": False,
    }
    body = body_en.strip()
    if not body:
        meta["final_wc"] = 0
        return body, meta

    if meta["initial_wc"] > max_words:
        meta["trimmed"] = True
    body = trim_english_to_max_words(body, max_words)

    wc = word_count(body)
    attempts = 0
    while wc < min_words and attempts < max_expand_attempts:
        prompt = _expand_prompt(body, wc, min_words, max_words)
        body = write_english_article(prompt).strip()
        attempts += 1
        body = trim_english_to_max_words(body, max_words)
        wc = word_count(body)

    meta["expand_attempts"] = attempts

    if wc < min_words:
        body = stretch_with_source_excerpts(body, sources, min_words)
        body = trim_english_to_max_words(body, max_words)
        meta["stretched_from_sources"] = word_count(body) > wc
        wc = word_count(body)

    meta["final_wc"] = wc
    return body, meta
