"""
Unified source schema for all ingested articles (NewsData.io, RSS, etc.).
Used when storing in Firestore `sources` collection.
"""
import hashlib
from datetime import datetime, timezone
from typing import Any


def make_content_hash(url: str, title: str) -> str:
    """Hash for deduplication. Same url+title -> same hash."""
    raw = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def make_source_id(prefix: str, url: str) -> str:
    """Unique source_id for a document."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def normalize_published_at(value: str | None) -> str:
    """Normalize to ISO 8601 or empty string."""
    if not value:
        return ""
    val = value.strip().replace("T", " ").replace("Z", "")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(val[: len(fmt)], fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            continue
    return value


# Unified source schema (dict) - all fields written to Firestore
def unified_source(
    *,
    source_id: str,
    title: str,
    url: str,
    publisher: str,
    published_at: str,
    snippet: str,
    source_type: str,
    topic: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Build a unified source document for Firestore."""
    snippet_trimmed = snippet[:800].rsplit(" ", 1)[0] + "..." if len(snippet) > 800 else snippet
    content_hash = make_content_hash(url, title)
    return {
        "source_id": source_id,
        "title": title,
        "url": url,
        "publisher": publisher,
        "published_at": published_at,
        "snippet": snippet_trimmed or title,
        "source_type": source_type,
        "topic": topic,
        "category": category,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
    }


def unified_to_bundle_source(s: dict[str, Any]) -> dict[str, Any]:
    """Convert unified source to bundle source format (for /admin/generate)."""
    return {
        "source_id": s.get("source_id", ""),
        "url": s.get("url", ""),
        "publisher": s.get("publisher", "Unknown"),
        "published_at": s.get("published_at", ""),
        "snippet": s.get("snippet", ""),
    }
