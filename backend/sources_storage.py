"""
Firestore storage for sources with deduplication.
"""
import hashlib
from google.cloud import firestore


SOURCES_COLLECTION = "sources"


def _url_doc_id(url: str) -> str:
    """Firestore doc ID from URL (for dedup by URL)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _title_normalized(title: str) -> str:
    """Normalize title for similarity check (lowercase, strip, truncate)."""
    return (title or "").strip().lower()[:100]


def is_duplicate(db: firestore.Client, source: dict) -> tuple[bool, str]:
    """
    Check if source already exists (by URL or very similar title).
    Returns (is_dup, reason).
    """
    url = source.get("url", "")
    if not url:
        return True, "missing_url"

    doc_id = _url_doc_id(url)
    doc = db.collection(SOURCES_COLLECTION).document(doc_id).get()
    if doc.exists:
        return True, "url_exists"

    # Optional: check for very similar title (exact match after normalize)
    title = _title_normalized(source.get("title", ""))
    if not title:
        return False, ""

    # Simple check: query by content_hash (same url+title)
    content_hash = source.get("content_hash", "")
    if content_hash:
        q = (
            db.collection(SOURCES_COLLECTION)
            .where("content_hash", "==", content_hash)
            .limit(1)
        )
        for d in q.stream():
            return True, "content_hash_exists"
    return False, ""


def save_sources(
    db: firestore.Client,
    sources: list[dict],
    skip_duplicates: bool = True,
) -> tuple[int, int]:
    """
    Save sources to Firestore. Deduplicates by URL.

    Returns:
        (saved_count, skipped_count)
    """
    saved = 0
    skipped = 0
    for s in sources:
        if skip_duplicates:
            is_dup, _ = is_duplicate(db, s)
            if is_dup:
                skipped += 1
                continue
        doc_id = _url_doc_id(s.get("url", ""))
        if not doc_id:
            skipped += 1
            continue
        db.collection(SOURCES_COLLECTION).document(doc_id).set(s)
        saved += 1
    return saved, skipped


def list_sources(
    db: firestore.Client,
    topic: str | None = None,
    source_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List sources, optionally filtered by topic or source_type."""
    q = db.collection(SOURCES_COLLECTION).limit(limit)
    if topic:
        q = q.where("topic", "==", topic)
    if source_type:
        q = q.where("source_type", "==", source_type)
    docs = list(q.stream())
    # Sort by ingested_at desc in memory (avoids composite index)
    docs.sort(key=lambda d: d.to_dict().get("ingested_at", ""), reverse=True)
    return [d.to_dict() for d in docs]
