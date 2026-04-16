"""
Create bundles from stored sources.
Improved: deduplicate similar sources, filter trivial snippets, keep 3–5 good sources.
"""
import random
import uuid
from datetime import datetime, timezone, timedelta
from google.cloud import firestore

try:
    from backend.source_schema import unified_to_bundle_source
except ImportError:
    from source_schema import unified_to_bundle_source


SOURCES_COLLECTION = "sources"
BUNDLES_COLLECTION = "bundles"

# Minimum snippet length to consider useful (avoid empty/trivial)
MIN_SNIPPET_LEN = 30
# Max sources from same publisher (avoid over-representing one outlet)
MAX_SAME_PUBLISHER = 2


def _normalize_for_similarity(s: str) -> str:
    """Normalize for title/snippet similarity check."""
    return (s or "").strip().lower()[:80]


def _is_duplicate_source(a: dict, b: dict) -> bool:
    """True if sources are obviously duplicated (same publisher + very similar title)."""
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
    for source_type in ("newsapi", "newsdata", "rss", "unknown"):
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
        "created_from": "sources",
    }
    db.collection(BUNDLES_COLLECTION).document(bundle_id).set(bundle)
    return {
        "ok": True,
        "bundle_id": bundle_id,
        "sources_count": len(bundle_sources),
        "topic": topic,
    }
