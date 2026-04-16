from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of backend/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
# override=True: .env wins over empty or placeholder vars in the shell (common on Windows).
load_dotenv(_env_path, override=True)

from fastapi import FastAPI
from pydantic import BaseModel
from google.cloud import firestore
import os
import re
import requests
import traceback
import uuid
from datetime import datetime, timezone

# Support running as "uvicorn main:app" from backend/ or "uvicorn backend.main:app" from root
try:
    from backend.translator import translate_en_to_az, translate_en_to_az_long
    from backend.text_writer import write_english_article
    from backend.gemini_client import gemini_configured
    from backend.prompts import build_writer_prompt
    from backend.article_validator import validate_article
    from backend.article_length_adjust import fit_english_body_to_word_range
    from backend.newsdata_client import (
        fetch_articles as fetch_newsdata_articles,
        fetch_articles_randomized as fetch_newsdata_articles_randomized,
        articles_to_bundle_sources,
        newsdata_to_unified_sources,
    )
    from backend.rss_client import fetch_rss, fetch_rss_random_feeds
    from backend.newsapi_client import (
        fetch_articles as fetch_newsapi_articles,
        fetch_articles_randomized as fetch_newsapi_articles_randomized,
        newsapi_to_unified_sources,
    )
    from backend.sources_storage import save_sources, list_sources
    from backend.bundle_creator import create_bundle_from_sources
except ImportError:
    from translator import translate_en_to_az, translate_en_to_az_long
    from text_writer import write_english_article
    from gemini_client import gemini_configured
    from prompts import build_writer_prompt
    from article_validator import validate_article
    from article_length_adjust import fit_english_body_to_word_range
    from newsdata_client import (
        fetch_articles as fetch_newsdata_articles,
        fetch_articles_randomized as fetch_newsdata_articles_randomized,
        articles_to_bundle_sources,
        newsdata_to_unified_sources,
    )
    from rss_client import fetch_rss, fetch_rss_random_feeds
    from newsapi_client import (
        fetch_articles as fetch_newsapi_articles,
        fetch_articles_randomized as fetch_newsapi_articles_randomized,
        newsapi_to_unified_sources,
    )
    from sources_storage import save_sources, list_sources
    from bundle_creator import create_bundle_from_sources

# Local dev: set USE_FIRESTORE_EMULATOR=1 (and optionally FIRESTORE_EMULATOR_HOST) in .env.
# GCP / Cloud Run: leave USE_FIRESTORE_EMULATOR unset; use real Firestore + GOOGLE_CLOUD_PROJECT.
if os.environ.get("USE_FIRESTORE_EMULATOR", "").strip().lower() in ("1", "true", "yes", "on"):
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8082")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "demo-no-project")
else:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", "demo-no-project"))


def _model_version_string() -> str:
    loc = "vertex" if os.environ.get("GEMINI_USE_VERTEX", "").strip().lower() in (
        "1", "true", "yes", "on",
    ) else "api"
    mid = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    return f"gemini:{mid} ({loc}) writer+translator"


app = FastAPI()
db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])

# Word count limits (Ollama can vary; 350–750 allows some flexibility)
MIN_WORDS = int(os.environ.get("ARTICLE_MIN_WORDS", "350"))
MAX_WORDS = int(os.environ.get("ARTICLE_MAX_WORDS", "750"))
ARTICLE_EXPAND_ATTEMPTS = int(os.environ.get("ARTICLE_EXPAND_ATTEMPTS", "4"))


@app.get("/admin/status")
def status():
    """Check which Firestore we're using (emulator vs prod) and env vars."""
    be = os.environ.get("AI_BACKEND", "auto")
    return {
        "firestore_emulator_host": os.environ.get("FIRESTORE_EMULATOR_HOST", ""),
        "use_firestore_emulator": os.environ.get("USE_FIRESTORE_EMULATOR", ""),
        "project": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        "newsdata_api_key_set": bool(os.environ.get("NEWSDATA_API_KEY", "").strip()),
        "ai_backend": be,
        "gemini_configured": gemini_configured(),
        "gemini_api_key_set": bool((os.environ.get("GEMINI_API_KEY") or "").strip()),
        "model_version": _model_version_string(),
    }


class GenerateRequest(BaseModel):
    bundle_id: str


class FetchBundleRequest(BaseModel):
    """Fetch articles from NewsData.io and create a bundle (legacy, direct to bundle)."""

    topic: str
    q: str | None = None  # Search query; defaults to topic
    language: str | None = "en"
    category: str | None = None  # e.g. "technology", "business", "world"
    mode: str = "explainer"
    max_sources: int = 10


class FetchRssRequest(BaseModel):
    """Fetch from RSS feed and store in sources."""

    url: str | None = None  # Default: TechCrunch; ignored when random_feeds is True
    topic: str | None = "technology"
    max_entries: int = 20
    # When True, pick random feeds from the catalog (mixed categories), merge, shuffle.
    random_feeds: bool = True
    random_feed_count: int = 3  # Number of distinct feeds (1–catalog size)


class FetchNewsdataRequest(BaseModel):
    """Fetch from NewsData.io and store in sources."""

    topic: str
    q: str | None = None
    language: str | None = "en"
    category: str | None = None
    max_sources: int = 10
    # When True, ignore q/category and fetch with random multi-category + optional broad q, shuffled.
    randomize: bool = True


class FetchNewsapiRequest(BaseModel):
    """Fetch from NewsAPI.org and store in sources."""

    topic: str
    q: str | None = None
    language: str | None = "en"
    max_sources: int = 10
    # When True, ignore q and fetch with random tech domains + optional broad q, shuffled.
    randomize: bool = True


class CreateBundleRequest(BaseModel):
    """Create bundle from stored sources."""

    topic: str
    mode: str = "explainer"
    max_sources: int = 5
    min_sources: int = 3
    days_back: int = 7


def write_english(bundle: dict) -> dict:
    """Generate English title and body using Gemini."""
    mode = bundle.get("mode", "explainer")
    topic = bundle.get("topic", "Technology")
    sources = bundle.get("sources", [])
    constraints = bundle.get("constraints", {})
    length_words = tuple(constraints.get("length_words", [400, 700]))
    prompt = build_writer_prompt(mode, topic, sources, length_words)
    body_en = write_english_article(prompt)
    topic = bundle.get("topic", "Tech")
    title_en = f"{topic}: Key Updates (Draft)"
    return {"title_en": title_en, "body_en": body_en}


def translate_to_az(text_en: str) -> str:
    """Translate English text to Azerbaijani (Gemini)."""
    return translate_en_to_az(text_en)


def split_body_and_sources(body_en: str) -> tuple[str, str]:
    """
    Split body into article content and Sources section.
    URLs are kept separate from the article for safety.
    """
    body = body_en.strip()
    # Match "Sources" or "Sources:" (case insensitive) followed by optional newlines
    match = re.search(r"\n\s*Sources:?\s*\n", body, re.IGNORECASE)
    if match:
        idx = match.start()
        article_part = body[:idx].strip()
        sources_part = body[idx:].strip()
        return article_part, sources_part
    # Fallback: detect lines that look like URLs (http/https)
    lines = body.split("\n")
    article_lines = []
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
        article_part = "\n".join(lines[:sources_start]).strip()
        sources_part = "\n".join(lines[sources_start:]).strip()
        return article_part, sources_part
    return body, ""


def translate_body_to_az(body_en: str) -> str:
    """
    Translate article body to Azerbaijani.
    Strips Sources section (URLs) before translation, then appends it with header "Mənbələr".
    """
    article_part, sources_part = split_body_and_sources(body_en)
    if not article_part:
        article_az = ""
    else:
        article_az = translate_en_to_az_long(article_part)
    if sources_part:
        # Replace "Sources:" with "Mənbələr:" and keep URLs as-is
        sources_az = "Mənbələr:\n" + re.sub(
            r"^Sources:?\s*\n?", "", sources_part, flags=re.IGNORECASE
        ).strip()
        return (article_az + "\n\n" + sources_az).strip() if article_az else sources_az
    return article_az


@app.post("/admin/bundles/fetch")
def fetch_bundle(req: FetchBundleRequest):
    """
    Fetch articles from NewsData.io and create a bundle.
    Requires NEWSDATA_API_KEY environment variable.
    """
    try:
        articles = fetch_newsdata_articles(
            q=req.q or req.topic,
            language=req.language,
            category=req.category,
            max_results=req.max_sources,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except requests.RequestException as e:
        return {"ok": False, "error": f"NewsData.io request failed: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if not articles:
        return {"ok": False, "error": "No articles found for the given query"}

    sources = articles_to_bundle_sources(articles)
    bundle_id = f"bundle_{uuid.uuid4().hex[:12]}"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    bundle = {
        "bundle_id": bundle_id,
        "date": date_str,
        "mode": req.mode,
        "topic": req.topic,
        "sources": sources,
        "constraints": {"length_words": [400, 700], "target_language": "az"},
        "fetched_from": "newsdata.io",
    }

    db.collection("bundles").document(bundle_id).set(bundle)
    return {
        "ok": True,
        "bundle_id": bundle_id,
        "sources_count": len(sources),
        "topic": req.topic,
    }


# --- Source ingestion + bundle creation pipeline ---

@app.get("/admin/sources")
def get_sources(topic: str | None = None, source_type: str | None = None, limit: int = 50):
    """List stored sources (for debugging)."""
    sources = list_sources(db, topic=topic, source_type=source_type, limit=limit)
    return {"ok": True, "sources": sources, "count": len(sources)}


@app.post("/admin/sources/fetch-rss")
def fetch_rss_sources(req: FetchRssRequest):
    """Fetch RSS feed and store in sources collection with deduplication."""
    try:
        if req.random_feeds:
            n = max(1, min(req.random_feed_count, 20))
            sources, feed_urls = fetch_rss_random_feeds(
                max_entries=req.max_entries,
                topic=req.topic,
                num_feeds=n,
                per_feed_cap=max(5, req.max_entries // max(1, n) + 5),
            )
            primary_url = feed_urls[0] if feed_urls else None
        else:
            url = req.url or "https://feeds.feedburner.com/TechCrunch"
            sources = fetch_rss(url, max_entries=req.max_entries, topic=req.topic)
            feed_urls = [url]
            primary_url = url
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not sources:
        return {"ok": False, "error": "No entries in RSS feed"}
    saved, skipped = save_sources(db, sources, skip_duplicates=True)
    out = {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "total_fetched": len(sources),
        "feed_url": primary_url,
        "random_feeds": req.random_feeds,
    }
    if req.random_feeds:
        out["feed_urls"] = feed_urls
    return out


@app.post("/admin/sources/fetch-newsdata")
def fetch_newsdata_sources(req: FetchNewsdataRequest):
    """Fetch from NewsData.io and store in sources collection with deduplication."""
    nd_meta: dict | None = None
    try:
        if req.randomize:
            articles, nd_meta = fetch_newsdata_articles_randomized(
                topic=req.topic,
                language=req.language,
                max_results=req.max_sources,
            )
        else:
            articles = fetch_newsdata_articles(
                q=req.q or req.topic,
                language=req.language,
                category=req.category,
                max_results=req.max_sources,
            )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except requests.RequestException as e:
        return {"ok": False, "error": f"NewsData.io request failed: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not articles:
        return {"ok": False, "error": "No articles found for the given query"}
    sources = newsdata_to_unified_sources(
        articles,
        topic=req.topic,
        category=req.category,
    )
    saved, skipped = save_sources(db, sources, skip_duplicates=True)
    out = {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "total_fetched": len(sources),
        "topic": req.topic,
        "randomize": req.randomize,
    }
    if nd_meta is not None:
        out["newsdata_pick"] = nd_meta
    return out


@app.post("/admin/sources/fetch-newsapi")
def fetch_newsapi_sources(req: FetchNewsapiRequest):
    """Fetch from NewsAPI.org and store in sources collection with deduplication."""
    na_meta: dict | None = None
    try:
        if req.randomize:
            articles, na_meta = fetch_newsapi_articles_randomized(
                topic=req.topic,
                language=req.language,
                max_results=req.max_sources,
            )
        else:
            articles = fetch_newsapi_articles(
                q=req.q or req.topic,
                language=req.language,
                page_size=req.max_sources,
            )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except requests.RequestException as e:
        return {"ok": False, "error": f"NewsAPI.org request failed: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not articles:
        return {"ok": False, "error": "No articles found for the given query"}
    sources = newsapi_to_unified_sources(
        articles,
        topic=req.topic,
        category="technology",  # NewsAPI doesn't have categories, default to technology
    )
    saved, skipped = save_sources(db, sources, skip_duplicates=True)
    out = {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "total_fetched": len(sources),
        "topic": req.topic,
        "randomize": req.randomize,
    }
    if na_meta is not None:
        out["newsapi_pick"] = na_meta
    return out


@app.get("/admin/bundles")
def list_bundles(limit: int = 20):
    """List bundle IDs (for testing and debugging)."""
    docs = db.collection("bundles").limit(limit).stream()
    bundles = []
    for d in docs:
        data = d.to_dict()
        bundles.append({
            "bundle_id": data.get("bundle_id", d.id),
            "mode": data.get("mode"),
            "topic": data.get("topic"),
            "sources_count": len(data.get("sources", [])),
        })
    return {"ok": True, "bundles": bundles}


@app.post("/admin/bundles/create")
def create_bundle(req: CreateBundleRequest):
    """Create a bundle from stored sources (by topic)."""
    result = create_bundle_from_sources(
        db,
        topic=req.topic,
        mode=req.mode,
        max_sources=req.max_sources,
        min_sources=req.min_sources,
        days_back=req.days_back,
    )
    return result


@app.post("/admin/generate")
def generate(req: GenerateRequest):
    bundle_ref = db.collection("bundles").document(req.bundle_id)
    bundle_doc = bundle_ref.get()
    if not bundle_doc.exists:
        return {"ok": False, "error": "Bundle not found"}

    bundle = bundle_doc.to_dict()
    sources = bundle.get("sources", [])

    try:
        # 1) Write in English (Gemini)
        out_en = write_english(bundle)
        body_en, length_meta = fit_english_body_to_word_range(
            out_en["body_en"],
            sources,
            min_words=MIN_WORDS,
            max_words=MAX_WORDS,
            max_expand_attempts=ARTICLE_EXPAND_ATTEMPTS,
        )
        out_en["body_en"] = body_en

        # 2) Translate to Azerbaijani (Gemini)
        title_az = translate_to_az(out_en["title_en"])
        body_az = translate_body_to_az(out_en["body_en"])

        # 3) Validate before storage (reject if checks fail)
        ok, details = validate_article(
            out_en["body_en"],
            body_az,
            sources,
            min_words_en=MIN_WORDS,
            max_words_en=MAX_WORDS,
            min_words_az=50,
        )
        if not ok:
            return {
                "ok": False,
                "error": "Article validation failed",
                "validation_errors": details["errors"],
                "flags": details.get("flags", {}),
                "length_adjustment": length_meta,
            }

        # First paragraph as lede
        lede_az = body_az.split("\n\n")[0].strip() if body_az else ""

        # 4) Store article
        article_id = f"art_{uuid.uuid4().hex[:10]}"
        article = {
            "article_id": article_id,
            "bundle_id": req.bundle_id,
            "mode": bundle.get("mode"),
            "topic": bundle.get("topic"),
            "ai_generated": True,
            "model_version": _model_version_string(),
            "title_en": out_en["title_en"],
            "body_en": out_en["body_en"],
            "title_az": title_az,
            "lede_az": lede_az,
            "body_az": body_az,
            "source_links": [s.get("url") for s in sources],
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "quality_flags": {**details.get("flags", {}), "length_adjustment": length_meta},
        }
        db.collection("articles").document(article_id).set(article)

        return {
            "ok": True,
            "article_id": article_id,
            "quality_flags": {**details.get("flags", {}), "length_adjustment": length_meta},
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "ok": False,
            "error": "Generation failed",
            "detail": str(e),
            "error_type": type(e).__name__,
        }


@app.get("/admin/articles/{article_id}")
def get_article(article_id: str):
    """Read back a generated article (for end-to-end test)."""
    doc = db.collection("articles").document(article_id).get()
    if not doc.exists:
        return {"ok": False, "error": "Article not found"}
    return {"ok": True, "article": doc.to_dict()}