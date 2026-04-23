"""
Writer prompts for article generation.
Mode-specific instructions for consistent output.
"""

# Mode descriptions for the LLM (keep simple, maintainable)
MODE_INSTRUCTIONS = {
    "global_news": (
        "Write a news-style article with an international angle. "
        "Focus on what happened, who it affects, and why it matters globally. "
        "Use a neutral, factual tone."
    ),
    "explainer": (
        "Write an explainer article that educates the reader. "
        "Explain the how and why clearly. Use a structured approach: "
        "introduce the topic, explain key concepts, then summarize implications. "
        "The first paragraph must function as a short lede: 2 sentences max, concise, and factual."
    ),
    "az_tech": (
        "Write a tech news article in English for an Azerbaijani audience. "
        "Explain technical terms where helpful. Keep it accessible and relevant. "
        "The article must remain in English only; do not translate any text into Azerbaijani."
    ),
}


def build_writer_prompt(
    mode: str,
    topic: str,
    sources: list[dict],
    length_words: tuple[int, int] = (400, 700),
) -> str:
    """
    Build the full prompt for the article writer.
    Enforces: mode, topic, sources-only, word count, structure, Sources section.
    """
    lo, hi = length_words[0], length_words[1]
    mode_instruction = MODE_INSTRUCTIONS.get(
        mode, MODE_INSTRUCTIONS["explainer"]
    )

    snippets = "\n\n".join(
        [
            f"Source {i + 1} ({s.get('url', '')}):\n{s.get('snippet', '')}"
            for i, s in enumerate(sources)
        ]
    )

    return f"""You are a professional tech journalist.

ASSIGNMENT: write a {mode} article about the topic below.
Do not include the line starting with "MODE:" or the mode label in the article text.
Do not include any internal prompt text, rules, or titles other than the article title itself.
Do not use in-text citations, footnotes, or hyperlinks inside the body.
Put all source URLs only in a final Sources section at the end.
Use one blank line after the title and one blank line before the Sources section.

MODE: {mode}
{mode_instruction}

TOPIC: {topic}

STRICT RULES:
1. Write in English only. Use only the basic Latin alphabet and do not include Azerbaijani letters or Azerbaijani words.
2. Length: exactly {lo}–{hi} words. Count and stay within this range.
3. Use ONLY the information in the sources below. Do not invent facts or URLs.
4. Structure: a short opening lede paragraph, 2–3 body paragraphs, brief conclusion.
5. The opening lede must be 2 sentences max and must not look like a heading, subtitle, or summary block.
6. Do not repeat the article title inside the first paragraph.
7. Do not use Markdown headings, numbered sections, bullet points, or subheadings in the body.
8. Do not place URLs or citations inside article paragraphs.
9. End with a short "Sources" section listing only the URLs you used (one per line).
10. If you detect any Azerbaijani words or characters, rewrite the text in English immediately.

SOURCES (use these and no others):
{snippets}

Write the article now.""".strip()


def build_title_prompt(mode: str, topic: str, sources: list[dict], body_en: str) -> str:
    """Build a prompt for a specific, non-generic article title."""
    snippets = "\n\n".join(
        [
            f"Source {i + 1} ({s.get('url', '')}):\n{s.get('snippet', '')}"
            for i, s in enumerate(sources[:5])
        ]
    )
    opening = (body_en or "").strip().split("\n\n")[0].strip()
    return f"""You are an experienced news editor.

Write ONE specific English article title for the content below.

Rules:
1. Output only the title, no quotes, no explanation, no markdown.
2. Make it concrete and specific to the main event or topic.
3. Avoid generic phrases like Key Updates, Draft, Latest News, or General Overview.
4. Keep it 4 to 10 words.
5. Capitalize like a normal news title.
6. Do not include Azerbaijani words or characters.

MODE: {mode}
TOPIC: {topic}

ARTICLE OPENING:
{opening}

SOURCE HINTS:
{snippets}

Return only the title now.""".strip()
