"""English → Azerbaijani: Gemini (GCP / API key)."""
import os

try:
    from backend.gemini_client import generate_content
except ImportError:
    from gemini_client import generate_content

_TRANSLATE_INSTRUCTION = """Translate the following English text into Azerbaijani using the Latin alphabet.
Preserve URLs, code tokens, and widely used English product names unchanged.
Output ONLY the Azerbaijani translation with no title, quotes, or preamble.

English:
"""


def translate_en_to_az(text_en: str) -> str:
    if not text_en or not text_en.strip():
        return ""
    prompt = _TRANSLATE_INSTRUCTION + text_en.strip()
    return generate_content(prompt, temperature=0.15, max_output_tokens=2048)


def translate_en_to_az_long(text_en: str, max_chunk_words: int | None = None) -> str:
    if not text_en or not text_en.strip():
        return ""
    total_words = len(text_en.split())
    single_call_max_words = int(os.environ.get("TRANSLATE_SINGLE_CALL_MAX_WORDS", "900"))

    # Fast path: one model call avoids per-paragraph overhead for normal article sizes.
    if total_words <= single_call_max_words:
        return generate_content(
            _TRANSLATE_INSTRUCTION + text_en.strip(),
            temperature=0.15,
            max_output_tokens=8192,
        )

    if max_chunk_words is None:
        max_chunk_words = int(os.environ.get("TRANSLATE_MAX_CHUNK_WORDS", "260"))
    # For long text, chunk and translate each chunk with Gemini
    paragraphs = [p.strip() for p in text_en.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    translated = []
    for para in paragraphs:
        if not para:
            continue
        words = para.split()
        if len(words) <= max_chunk_words:
            try:
                result = generate_content(
                    _TRANSLATE_INSTRUCTION + para.strip(),
                    temperature=0.15,
                    max_output_tokens=2048,
                )
                translated.append(result)
            except Exception as e:
                import traceback
                print(f"Error translating paragraph: {e}")
                traceback.print_exc()
                translated.append(para)  # Keep original if translation fails
        else:
            # Split long paragraph into chunks
            chunks = []
            current = []
            for w in words:
                current.append(w)
                if len(current) >= max_chunk_words:
                    chunks.append(" ".join(current))
                    current = []
            if current:
                chunks.append(" ".join(current))
            for chunk in chunks:
                try:
                    result = generate_content(
                        _TRANSLATE_INSTRUCTION + chunk.strip(),
                        temperature=0.15,
                        max_output_tokens=2048,
                    )
                    translated.append(result)
                except Exception as e:
                    import traceback
                    print(f"Error translating chunk: {e}")
                    traceback.print_exc()
                    translated.append(chunk)  # Keep original if translation fails
    return "\n\n".join(translated)
