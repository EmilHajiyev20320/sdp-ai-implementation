"""Article writer: Gemini (GCP / API key)."""
import re

try:
    from backend.gemini_client import generate_content
except ImportError:
    from gemini_client import generate_content


def _looks_like_azerbaijani(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[əğışöçuƏĞİŞÖÇÜ]", text))


def translate_to_english(text: str) -> str:
    if not text or not text.strip():
        return ""
    prompt = (
        "Translate the following text to English only. Preserve any URLs and the Sources section exactly. "
        "Do not invent new facts or change the meaning. If the text is already English, return it unchanged."
        f"\n\nTEXT:\n{text.strip()}"
    )
    return generate_content(prompt, temperature=0.15, max_output_tokens=8192)


def write_english_article(prompt: str) -> str:
    retry_instruction = (
        "\n\nIMPORTANT: Generate the entire article in English only. "
        "Do not use any Azerbaijani characters or Azerbaijani words such as və, ilə, də, ki, bir, bu, hər, sizin, bizim, onun, Azərbaycan, Bakı. "
        "Use only the basic Latin alphabet and no special Azerbaijani letters."
    )

    body = generate_content(prompt, temperature=0.7, max_output_tokens=8192)
    if _looks_like_azerbaijani(body):
        body = generate_content(
            prompt + retry_instruction + "\n\nIf any non-English text appears, rewrite it in English.",
            temperature=0.2,
            max_output_tokens=8192,
        )
    if _looks_like_azerbaijani(body):
        body = translate_to_english(body)
    return body
