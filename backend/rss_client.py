"""
RSS feed fetcher. Normalizes entries into unified source schema.
"""
import random
import re
import feedparser

try:
    from backend.source_schema import (
        make_source_id,
        normalize_published_at,
        unified_source,
    )
except ImportError:
    from source_schema import (
        make_source_id,
        normalize_published_at,
        unified_source,
    )

# Default tech RSS feed for testing
DEFAULT_RSS_URL = "https://feeds.feedburner.com/TechCrunch"

# Tech-only public feeds; ``category`` is a broader tech sub-field for variety (not general news).
RSS_FEED_CATALOG: list[dict[str, str]] = [
    {"url": "https://feeds.feedburner.com/TechCrunch", "category": "tech_industry"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "category": "tech_policy_security"},
    {"url": "https://www.wired.com/feed/rss", "category": "tech_culture_science"},
    {"url": "https://www.theverge.com/rss/index.xml", "category": "consumer_tech"},
    {"url": "https://hnrss.org/frontpage", "category": "developer_community"},
    {"url": "https://www.theguardian.com/technology/rss", "category": "tech_society"},
    {"url": "https://www.technologyreview.com/feed/", "category": "emerging_tech"},
    {"url": "https://spectrum.ieee.org/rss/fulltext", "category": "engineering_hardware"},
    {"url": "https://venturebeat.com/feed/", "category": "tech_business_ai"},
    {"url": "https://www.techradar.com/rss", "category": "gadgets_software"},
    {"url": "https://www.theregister.com/headlines.atom", "category": "enterprise_it"},
    {"url": "https://9to5mac.com/feed/", "category": "mobile_platforms"},
    {"url": "https://www.zdnet.com/news/rss.xml", "category": "enterprise_it"},
    {"url": "https://www.engadget.com/rss.xml", "category": "consumer_gadgets"},
    {"url": "https://www.cnet.com/rss/news/", "category": "consumer_electronics"},
    {"url": "https://www.fastcompany.com/section/technology/rss", "category": "innovation"},
]


def fetch_rss(
    url: str,
    max_entries: int = 20,
    topic: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Fetch RSS feed and return list of unified source dicts.

    Args:
        url: RSS feed URL
        max_entries: Max entries to return
        topic: Optional topic label stored on the source
        category: Stored category; defaults to topic when omitted

    Returns:
        List of unified source dicts (not yet stored in Firestore)
    """
    parsed = feedparser.parse(url, request_headers={"User-Agent": "AI-Publisher/1.0"})
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"RSS parse error for {url}: {getattr(parsed.bozo_exception, 'message', 'unknown')}")

    feed_title = getattr(parsed.feed, "title", "") or "Unknown"
    sources = []
    for i, entry in enumerate(parsed.entries[:max_entries]):
        link = getattr(entry, "link", "") or getattr(entry, "id", "")
        if not link:
            continue

        title = getattr(entry, "title", "") or "Untitled"
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or title
        if hasattr(summary, "replace"):
            summary = re.sub(r"<[^>]+>", " ", summary)[:800]
        else:
            summary = str(summary)[:800]

        pub = getattr(entry, "published", "") or getattr(entry, "updated", "")
        published_at = normalize_published_at(pub) if pub else ""

        src = unified_source(
            source_id=make_source_id("rss", link),
            title=title,
            url=link,
            publisher=feed_title,
            published_at=published_at,
            snippet=summary,
            source_type="rss",
            topic=topic,
            category=category if category is not None else topic,
        )
        sources.append(src)
    return sources


def fetch_rss_random_feeds(
    max_entries: int = 20,
    topic: str | None = None,
    num_feeds: int = 2,
    per_feed_cap: int = 15,
    rng: random.Random | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Fetch from ``num_feeds`` distinct random catalog feeds, merge, dedupe by URL,
    shuffle, then return up to ``max_entries`` sources.

    Returns:
        (sources, feed_urls_used)
    """
    rng = rng or random.Random()
    n = max(1, min(num_feeds, len(RSS_FEED_CATALOG)))
    picks = rng.sample(RSS_FEED_CATALOG, k=n)
    merged: list[dict] = []
    seen_urls: set[str] = set()
    urls_used: list[str] = []

    for feed in picks:
        url = feed["url"]
        cat = feed["category"]
        urls_used.append(url)
        batch = fetch_rss(
            url,
            max_entries=per_feed_cap,
            topic=topic,
            category=cat,
        )
        for s in batch:
            u = (s.get("url") or "").strip()
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            merged.append(s)

    rng.shuffle(merged)
    return merged[:max_entries], urls_used
