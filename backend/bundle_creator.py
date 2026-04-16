"""
Create bundles from stored sources.
Improved: deduplicate similar sources, filter trivial snippets, keep 3–5 good sources.
"""
import random
import uuid
import re
from datetime import datetime, timezone, timedelta
from google.cloud import firestore

try:
    from backend.source_schema import unified_to_bundle_source
except ImportError:
    from source_schema import unified_to_bundle_source


SOURCES_COLLECTION = "sources"
RAW_ARTICLES_COLLECTION = "raw_articles"
BUNDLES_COLLECTION = "bundles"

# Minimum snippet length to consider useful (avoid empty/trivial)
MIN_SNIPPET_LEN = 30
# Max sources from same publisher (avoid over-representing one outlet)
MAX_SAME_PUBLISHER = 2
# In explainer mode, try to enrich with several pre-scraped raw articles
EXPLAINER_RAW_MAX_SOURCES = 4


def _normalize_for_similarity(s: str) -> str:
    """Normalize for title/snippet similarity check."""
    return (s or "").strip().lower()[:80]


def _is_duplicate_source(a: dict, b: dict) -> bool:
    """True if sources are obviously duplicated (same publisher + very similar title)."""
    url_a = (a.get("url") or "").strip().lower()
    url_b = (b.get("url") or "").strip().lower()
    if url_a and url_b and url_a == url_b:
        return True

    pub_a = _normalize_for_similarity(a.get("publisher", ""))
    pub_b = _normalize_for_similarity(b.get("publisher", ""))
    if pub_a != pub_b:
        return False
    title_a = _normalize_for_similarity(a.get("title", ""))
    title_b = _normalize_for_similarity(b.get("title", ""))
    if not title_a or not title_b:
        return False
    # Same publisher + titles share most words
    words_a = set(title_a.split())
    words_b = set(title_b.split())
    overlap = len(words_a & words_b) / max(len(words_a), 1)
    return overlap >= 0.7


def _normalize_date_yyyy_mm_dd(value) -> str:
    """Best-effort date extraction for Firestore string/timestamp variants."""
    if not value:
        return ""

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d")

    s = str(value).strip()
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        return s[:10]

    match = re.search(r"([A-Za-z]+\s+\d{1,2},\s+\d{4})", s)
    if match:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    return ""


def _raw_article_to_unified(doc_id: str, raw: dict, topic: str) -> dict | None:
    """Map raw_articles documents to unified source schema expected by bundle builder."""
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or raw.get("uri") or "").strip()
    if not title or not url:
        return None

    snippet = (raw.get("snippet") or raw.get("content") or title).strip()
    if len(snippet) > 800:
        snippet = snippet[:800].rsplit(" ", 1)[0] + "..."

    content_hash = (raw.get("content_hash") or "").strip()
    source_id = (raw.get("source_id") or f"raw_{(content_hash or doc_id)[:12]}").strip()
    return {
        "source_id": source_id,
        "title": title,
        "url": url,
        "publisher": (raw.get("publisher") or "Unknown").strip() or "Unknown",
        "published_at": str(raw.get("published_at") or ""),
        "snippet": snippet,
        "source_type": (raw.get("source_type") or "raw_articles").strip().lower(),
        "topic": (raw.get("topic") or topic or "").strip(),
        "category": (raw.get("category") or topic or "").strip(),
        "content_hash": content_hash,
        "processed": bool(raw.get("processed", False)),
    }


def _fetch_raw_article_sources(db: firestore.Client, topic: str, cutoff: str, limit: int) -> list[dict]:
    """Fetch and normalize additional sources from raw_articles for explainer mode."""
    docs = list(
        db.collection(RAW_ARTICLES_COLLECTION)
        .where("topic", "==", topic)
        .limit(limit * 3)
        .stream()
    )

    if len(docs) < limit:
        extra = db.collection(RAW_ARTICLES_COLLECTION).where("category", "==", topic).limit(limit * 3).stream()
        seen_ids = {d.id for d in docs}
        for d in extra:
            if d.id not in seen_ids:
                docs.append(d)
                seen_ids.add(d.id)

    out: list[dict] = []
    for d in docs:
        src = _raw_article_to_unified(d.id, d.to_dict() or {}, topic)
        if not src:
            continue
        pub_day = _normalize_date_yyyy_mm_dd(src.get("published_at", ""))
        # Include if recent enough, or if date is missing/unparseable.
        if not pub_day or pub_day >= cutoff:
            out.append(src)

    # Prefer not-yet-processed raw items first.
    out.sort(key=lambda s: (s.get("processed", False),), reverse=False)
    return out[:limit]


def _filter_and_dedupe_sources(sources: list[dict], max_sources: int) -> list[dict]:
    """
    Filter out trivial snippets, deduplicate similar sources, limit same publisher.
    """
    # 1) Keep only sources with useful snippet
    filtered = [s for s in sources if len((s.get("snippet") or "").strip()) >= MIN_SNIPPET_LEN]
    if not filtered:
        filtered = sources  # fallback if all snippets empty

    # 2) Deduplicate: keep first of each "similar" pair
    seen: list[dict] = []
    for s in filtered:
        if any(_is_duplicate_source(s, x) for x in seen):
            continue
        seen.append(s)

    # 3) Limit same publisher: prefer variety
    by_publisher: dict[str, list[dict]] = {}
    for s in seen:
        pub = (s.get("publisher") or "Unknown").strip() or "Unknown"
        by_publisher.setdefault(pub, []).append(s)
    result = []
    for pub, items in by_publisher.items():
        result.extend(items[:MAX_SAME_PUBLISHER])
    random.shuffle(result)
    return result[:max_sources]


def _select_diverse_sources(sources: list[dict], max_sources: int) -> list[dict]:
    """Prefer one source from each source_type when possible."""
    selected = []
    seen_types: set[str] = set()
    for source_type in ("newsapi", "newsdata", "rss", "raw_articles", "unknown"):
        for s in sources:
            t = (s.get("source_type") or "unknown").strip().lower()
            if t == source_type and s not in selected:
                selected.append(s)
                seen_types.add(t)
                break
        if len(selected) >= max_sources:
            return selected

    for s in sources:
        if len(selected) >= max_sources:
            break
        if s not in selected:
            selected.append(s)
    return selected


def create_bundle_from_sources(
    db: firestore.Client,
    topic: str,
    mode: str = "explainer",
    max_sources: int = 5,
    min_sources: int = 3,
    days_back: int = 7,
) -> dict:
    """
    Select sources by topic, create a bundle.

    Args:
        db: Firestore client
        topic: Topic to filter (matches source.topic or source.category)
        mode: Bundle mode (explainer, etc.)
        max_sources: Max sources per bundle
        min_sources: Min sources required
        days_back: Only consider sources from last N days

    Returns:
        Bundle dict with bundle_id, or error
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    q = (
        db.collection(SOURCES_COLLECTION)
        .where("topic", "==", topic)
        .limit(max_sources * 3)  # fetch extra in case some filtered out
    )
    docs = list(q.stream())
    # Also try category for RSS (we store topic in both)
    if len(docs) < min_sources:
        q2 = (
            db.collection(SOURCES_COLLECTION)
            .where("category", "==", topic)
            .limit(max_sources * 3)
        )
        seen_ids = {d.id for d in docs}
        for d in q2.stream():
            if d.id not in seen_ids:
                docs.append(d)
                seen_ids.add(d.id)

    sources = []
    for d in docs:
        s = d.to_dict()
        pub = (s.get("published_at") or "")[:10]
        # Include if published within cutoff, or if no date (e.g. some RSS)
        if not pub or pub >= cutoff:
            sources.append(s)

    raw_sources: list[dict] = []
    if (mode or "").strip().lower() == "explainer":
        raw_sources = _fetch_raw_article_sources(
            db,
            topic=topic,
            cutoff=cutoff,
            limit=max(max_sources, EXPLAINER_RAW_MAX_SOURCES),
        )
        sources.extend(raw_sources)

    if len(sources) < min_sources:
        return {
            "ok": False,
            "error": f"Not enough sources for topic '{topic}': found {len(sources)}, need {min_sources}",
        }

    # Filter, dedupe, diversify publishers, then shuffle
    selected = _filter_and_dedupe_sources(sources, max_sources)
    selected = _select_diverse_sources(selected, max_sources)
    if len(selected) < min_sources:
        selected = sources[:max_sources]  # fallback if filtering too aggressive
        random.shuffle(selected)

    bundle_id = f"bundle_{uuid.uuid4().hex[:12]}"
    bundle_sources = [unified_to_bundle_source(s) for s in selected]

    bundle = {
        "bundle_id": bundle_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "mode": mode,
        "topic": topic,
        "sources": bundle_sources,
        "constraints": {"length_words": [400, 700], "target_language": "az"},
        "created_from": "sources+raw_articles" if raw_sources else "sources",
    }
    db.collection(BUNDLES_COLLECTION).document(bundle_id).set(bundle)
    return {
        "ok": True,
        "bundle_id": bundle_id,
        "sources_count": len(bundle_sources),
        "raw_sources_used": sum(1 for s in selected if (s.get("source_type") or "").strip().lower() == "raw_articles"),
        "topic": topic,
    }
