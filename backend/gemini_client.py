"""
Gemini text generation via Google AI Studio (API key) or Vertex AI (GCP / Cloud Run ADC).

Env:
  AI_BACKEND=gemini — use Gemini for writer + translator (with auto-detect below).
  GEMINI_API_KEY — Google AI Studio key (generative language API).
  GEMINI_USE_VERTEX=1 — use Vertex AI; needs GOOGLE_CLOUD_PROJECT, GEMINI_LOCATION (default us-central1).
  GEMINI_MODEL — preferred model id (optional; see https://ai.google.dev/gemini-api/docs/models).
  GEMINI_MODEL_FALLBACK=0 — disable trying alternate model ids on 404 (default: fallbacks on).

Unversioned ids (e.g. gemini-1.5-flash) often return 404 on v1beta for new keys; we try a fallback chain.
"""
from __future__ import annotations

import os
from typing import Any

# Try in order after GEMINI_MODEL (if set). IDs change; adjust from official model list.
_API_MODEL_FALLBACKS: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash",
]


def _use_vertex() -> bool:
    return os.environ.get("GEMINI_USE_VERTEX", "").strip().lower() in ("1", "true", "yes", "on")


def _default_model() -> str:
    explicit = (os.environ.get("GEMINI_MODEL") or "").strip()
    if explicit:
        return explicit
    return "gemini-2.5-flash"


def _api_model_try_order() -> list[str]:
    preferred = (os.environ.get("GEMINI_MODEL") or "").strip()
    chain = [preferred] if preferred else []
    chain.extend(_API_MODEL_FALLBACKS)
    seen: set[str] = set()
    out: list[str] = []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _is_model_not_found(err: BaseException) -> bool:
    msg = str(err).lower()
    if "404" in msg and "model" in msg:
        return True
    if "not found" in msg and ("model" in msg or "models/" in msg):
        return True
    try:
        from google.api_core import exceptions as gexc

        return isinstance(err, gexc.NotFound)
    except ImportError:
        return False


def _response_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return str(t).strip()
    except (ValueError, AttributeError):
        pass
    parts: list[str] = []
    cands = getattr(response, "candidates", None) or []
    for c in cands:
        content = getattr(c, "content", None)
        if not content:
            continue
        for p in getattr(content, "parts", []) or []:
            txt = getattr(p, "text", None)
            if txt:
                parts.append(txt)
    return "".join(parts).strip()


def _raise_if_blocked_or_empty(response: Any, model_id: str) -> None:
    """Raise RuntimeError with context when the model returns no usable text."""
    text = _response_text(response)
    if text:
        return
    feedback = getattr(response, "prompt_feedback", None)
    reason = getattr(feedback, "block_reason", None) if feedback else None
    msg = f"Gemini model {model_id!r} returned no text."
    if reason:
        msg += f" block_reason={reason!r}."
    if feedback and getattr(feedback, "safety_ratings", None):
        msg += f" safety_ratings={feedback.safety_ratings!r}."
    cands = getattr(response, "candidates", None) or []
    if cands:
        fr = getattr(cands[0], "finish_reason", None)
        if fr:
            msg += f" finish_reason={fr!r}."
    raise RuntimeError(msg)


def generate_content(
    prompt: str,
    *,
    temperature: float = 0.7,
    max_output_tokens: int = 8192,
) -> str:
    """Single-turn text generation; returns trimmed text or raises on failure."""
    prompt = (prompt or "").strip()
    if not prompt:
        return ""

    if _use_vertex():
        model_id = _default_model()
        import vertexai
        from vertexai.generative_models import GenerativeModel, GenerationConfig

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required when GEMINI_USE_VERTEX=1")
        location = os.environ.get("GEMINI_LOCATION", "us-central1").strip()
        vertexai.init(project=project, location=location)
        model = GenerativeModel(model_id)
        cfg = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        response = model.generate_content(prompt, generation_config=cfg)
        _raise_if_blocked_or_empty(response, model_id)
        return _response_text(response)

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is required for Gemini (Google AI Studio), or set GEMINI_USE_VERTEX=1 for Vertex AI."
        )

    import google.genai as genai

    client = genai.Client(api_key=api_key)
    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    fallbacks_on = os.environ.get("GEMINI_MODEL_FALLBACK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    candidates = _api_model_try_order() if fallbacks_on else [_default_model()]
    last_err: BaseException | None = None
    for mid in candidates:
        try:
            response = client.models.generate_content(
                model=mid,
                contents=prompt,
                config=config,
            )
            _raise_if_blocked_or_empty(response, mid)
            return _response_text(response)
        except Exception as e:
            if fallbacks_on and _is_model_not_found(e):
                last_err = e
                continue
            raise
    raise RuntimeError(
        "No Gemini model worked for this API key. Set GEMINI_MODEL to an id from "
        "https://ai.google.dev/gemini-api/docs/models — last error: "
        f"{last_err!s}"
    ) from last_err


def gemini_configured() -> bool:
    if _use_vertex():
        return bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip())
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())
