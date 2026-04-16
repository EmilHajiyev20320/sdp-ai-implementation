"""
Lightweight validation for generated articles before storage.
Rejects or flags articles that fail quality checks.
"""
import re
from typing import Any


def word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split()) if text else 0


# Default thresholds (can be overridden via env in main.py)
MIN_WORDS_EN = 350
MAX_WORDS_EN = 750
MIN_WORDS_AZ = 50
MIN_SOURCES = 1
MAX_REPEATED_PHRASE_LEN = 5
MAX_REPEATED_PHRASE_OCCURRENCES = 4  # Reject only when phrase appears 4+ times


def check_repetition(text: str, phrase_len: int = 5, max_occurrences: int = 3) -> tuple[bool, str]:
    """
    Check for degenerate repetition (same phrase repeated too many times).
    Returns (ok, message). ok=False means reject.
    """
    if not text or len(text) < 100:
        return True, ""
    words = text.split()
    if len(words) < phrase_len * max_occurrences:
        return True, ""
    # Sliding window: count occurrences of each phrase
    phrase_counts: dict[str, int] = {}
    for i in range(len(words) - phrase_len + 1):
        phrase = " ".join(words[i : i + phrase_len]).lower()
        phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
    for phrase, count in phrase_counts.items():
        if count >= max_occurrences:
            return False, f"Repeated phrase ({phrase[:50]}...) appears {count} times"
    return True, ""


def check_translation_ok(
    text_az: str,
    min_words: int = MIN_WORDS_AZ,
) -> tuple[bool, str]:
    """Check Azerbaijani translation is substantial."""
    if not text_az or not text_az.strip():
        return False, "Translation is empty"
    wc = word_count(text_az)
    if wc < min_words:
        return False, f"Translation too short: {wc} words (min {min_words})"
    return True, ""


def check_sources_present(sources: list[dict], min_count: int = MIN_SOURCES) -> tuple[bool, str]:
    """Check bundle has required sources."""
    if not sources:
        return False, "No sources attached"
    valid = [s for s in sources if s.get("url") or s.get("snippet")]
    if len(valid) < min_count:
        return False, f"Too few valid sources: {len(valid)} (min {min_count})"
    return True, ""


def validate_article(
    body_en: str,
    body_az: str,
    sources: list[dict],
    min_words_en: int = MIN_WORDS_EN,
    max_words_en: int = MAX_WORDS_EN,
    min_words_az: int = MIN_WORDS_AZ,
) -> tuple[bool, dict[str, Any]]:
    """
    Run all validation checks. Returns (ok, details).
    details contains: ok, errors[], flags{}, word_count_en, word_count_az, etc.
    """
    errors: list[str] = []
    flags: dict[str, Any] = {}

    wc_en = word_count(body_en)
    wc_az = word_count(body_az)
    flags["word_count_en"] = wc_en
    flags["word_count_az"] = wc_az
    flags["has_sources"] = len(sources) > 0
    flags["sources_count"] = len(sources)

    # 1) English length
    if wc_en < min_words_en:
        errors.append(f"English article too short: {wc_en} words (min {min_words_en})")
    elif wc_en > max_words_en:
        errors.append(f"English article too long: {wc_en} words (max {max_words_en})")
    else:
        flags["within_length"] = True

    # 2) Translation
    ok_az, msg_az = check_translation_ok(body_az, min_words=min_words_az)
    if not ok_az:
        errors.append(msg_az)
    else:
        flags["translation_ok"] = True

    # 3) Sources
    ok_src, msg_src = check_sources_present(sources)
    if not ok_src:
        errors.append(msg_src)
    else:
        flags["sources_ok"] = True

    # 4) Repetition (English)
    ok_rep, msg_rep = check_repetition(
        body_en,
        phrase_len=MAX_REPEATED_PHRASE_LEN,
        max_occurrences=MAX_REPEATED_PHRASE_OCCURRENCES,
    )
    if not ok_rep:
        errors.append(f"Degenerate repetition: {msg_rep}")
    else:
        flags["no_excessive_repetition"] = True

    return len(errors) == 0, {"ok": len(errors) == 0, "errors": errors, "flags": flags}
