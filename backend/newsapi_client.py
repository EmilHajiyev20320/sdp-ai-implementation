"""
NewsAPI.org client for fetching news articles.
Requires NEWSAPI_API_KEY environment variable.
Docs: https://newsapi.org/docs/endpoints/everything
"""
import os
import random
import requests
from datetime import datetime

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

BASE_URL = "https://newsapi.org/v2/everything"

# NewsAPI.org category codes — tech-adjacent only (comma-separated allowed).
# ``technology`` is always included when randomizing; others add breadth (R&D, industry context).
NEWSAPI_TECH_CATEGORY_EXTRAS = ["science", "business", "entertainment"]

# Keyword queries: broader sub-fields within technology (optional ``q`` with category filter).
NEWSAPI_TECH_QUERIES = [
    None,
    None,
    "artificial intelligence",
    "semiconductor",
    "cybersecurity",
    "cloud computing",
    "machine learning",
    "open source software",
    "quantum computing",
    "robotics",
    "data center",
    "startup technology",
    "smartphone",
    "privacy technology",
    "enterprise software",
    "autonomous vehicle",
    "developer tools",
    "renewable energy technology",
    "space technology",
    "blockchain",
    "chip manufacturing",
    "SaaS",
    "metaverse",
    "digital health",
    "edge computing",
    "fintech",
    "AI regulation",
]


def fetch_articles(
    q: str | None = None,
    language: str | None = "en",
    domains: str | None = None,
    exclude_domains: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sort_by: str = "publishedAt",
    page_size: int = 10,
) -> list[dict]:
    """
    Fetch news articles from NewsAPI.org.

    Args:
        q: Keywords or phrases to search for.
        language: 2-letter ISO-639-1 code (e.g. "en").
        domains: Comma-separated domains to restrict search to.
        exclude_domains: Comma-separated domains to exclude.
        from_date: Oldest article date (ISO 8601).
        to_date: Newest article date (ISO 8601).
        sort_by: Sort order (relevancy, popularity, publishedAt).
        page_size: Number of results per page (max 100).

    Returns:
        List of article dicts.
    """
    api_key = (os.environ.get("NEWSAPI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("NEWSAPI_API_KEY environment variable is required")

    params: dict = {"apiKey": api_key}
    if q:
        params["q"] = q
    if language:
        params["language"] = language
    if domains:
        params["domains"] = domains
    if exclude_domains:
        params["excludeDomains"] = exclude_domains
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    params["sortBy"] = sort_by
    params["pageSize"] = min(page_size, 100)

    r = requests.get(BASE_URL, params=params, timeout=30)
    if r.status_code == 401:
        raise RuntimeError(
            "NewsAPI.org 401 Unauthorized: Check your API key at https://newsapi.org - "
            "ensure it's correct and active."
        )
    r.raise_for_status()
    data = r.json()

    if data.get("status") != "ok":
        raise RuntimeError(
            f"NewsAPI.org API error: {data.get('message', data.get('code', 'Unknown'))}"
        )

    return data.get("articles", [])


def fetch_articles_randomized(
    *,
    topic: str | None = None,
    language: str | None = "en",
    max_results: int = 10,
    rng: random.Random | None = None,
) -> tuple[list[dict], dict]:
    """
    Random tech-focused fetch: NewsAPI domains/categories always include tech sources,
    plus optional tech sub-field query, then shuffle results.

    Returns:
        (articles, meta) where meta includes chosen domains and q for logging/UI.
    """
    rng = rng or random.Random()

    # Use tech-focused domains instead of categories (NewsAPI doesn't have categories like NewsData)
    tech_domains = [
        "techcrunch.com",
        "wired.com",
        "theverge.com",
        "arstechnica.com",
        "zdnet.com",
        "cnet.com",
        "engadget.com",
        "venturebeat.com",
        "theregister.com",
        "techradar.com",
    ]

    pool = list(NEWSAPI_TECH_QUERIES)
    if topic and topic.strip():
        t = topic.strip().lower()
        if t not in {"technology", "tech"}:
            pool.extend([topic.strip(), None])

    rounds = 2 if max_results <= 10 else 3
    merged: list[dict] = []
    seen_urls: set[str] = set()
    picks: list[dict] = []

    for i in range(rounds):
        chosen_domains = rng.sample(tech_domains, k=min(5, len(tech_domains)))
        domains_param = ",".join(chosen_domains)

        q_choice = rng.choice(pool)
        if q_choice is None and topic and topic.strip() and rng.random() < 0.35:
            q_choice = topic.strip()

        batch = fetch_articles(
            q=q_choice,
            language=language,
            domains=domains_param,
            page_size=max(10, max_results),
            sort_by="publishedAt" if i % 2 == 0 else "relevancy",
        )
        picks.append({"domains": chosen_domains, "domains_param": domains_param, "q": q_choice})
        for art in batch:
            url = (art.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(art)

    articles = list(merged)
    rng.shuffle(articles)
    meta = {
        "picks": picks,
        "distinct_articles": len(articles),
        "tech_focus": True,
    }
    return articles[:max_results], meta


def newsapi_to_unified_sources(
    articles: list[dict],
    topic: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Convert NewsAPI.org API response to unified source schema."""
    sources = []
    for i, art in enumerate(articles):
        link = art.get("url", "")
        if not link:
            continue
        snippet = art.get("description") or art.get("content") or art.get("title", "")
        pub = art.get("publishedAt", "")
        src = unified_source(
            source_id=make_source_id("na", link),
            title=art.get("title", "Untitled"),
            url=link,
            publisher=art.get("source", {}).get("name", "Unknown"),
            published_at=normalize_published_at(pub),
            snippet=snippet,
            source_type="newsapi",
            topic=topic,
            category=category or "technology",  # Default to technology
        )
        sources.append(src)
    return sources


def articles_to_bundle_sources(articles: list[dict]) -> list[dict]:
    """
    Convert NewsAPI.org articles to bundle source format.

    Bundle source format: {source_id, url, publisher, published_at, snippet}
    """
    sources = []
    for i, art in enumerate(articles):
        snippet = art.get("description") or art.get("content") or ""
        if len(snippet) > 800:
            snippet = snippet[:800].rsplit(" ", 1)[0] + "..."

        pub_date = art.get("publishedAt", "")
        if pub_date and "T" in pub_date:
            try:
                dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                pub_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        sources.append(
            {
                "source_id": art.get("source", {}).get("id", f"na_{i}"),
                "url": art.get("url", ""),
                "publisher": art.get("source", {}).get("name", "Unknown"),
                "published_at": pub_date,
                "snippet": snippet or art.get("title", ""),
            }
        )
    return sources