"""
NewsData.io API client for fetching news articles.
Requires NEWSDATA_API_KEY environment variable.
Docs: https://newsdata.io/documentation
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

BASE_URL = "https://newsdata.io/api/1/latest"

# NewsData.io category codes — tech-adjacent only (comma-separated allowed; up to 5 on free/basic).
# ``technology`` is always included when randomizing; others add breadth (R&D, industry context).
NEWSDATA_TECH_CATEGORY_EXTRAS = ["science", "business", "top", "world"]

# Keyword queries: broader sub-fields within technology (optional ``q`` with category filter).
NEWSDATA_TECH_QUERIES = [
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
    category: str | None = None,
    domain: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Fetch news articles from NewsData.io.

    Args:
        q: Search query (optional; omit for category-only discovery per API docs).
        language: Language code (e.g. "en" for English). None = all languages.
        category: Category filter (e.g. "technology", "business", "world"); comma-separated for several.
        domain: Filter by domain (e.g. "techcrunch.com")
        max_results: Max articles to return (free tier: 10 per request)

    Returns:
        List of article dicts with: article_id, title, link, description, content,
        pubDate, source_id, source_name, source_url
    """
    api_key = (os.environ.get("NEWSDATA_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("NEWSDATA_API_KEY environment variable is required")

    params: dict = {"apikey": api_key}
    if q:
        params["q"] = q
    if language:
        params["language"] = language
    if category:
        params["category"] = category
    if domain:
        params["domain"] = domain

    r = requests.get(BASE_URL, params=params, timeout=30)
    if r.status_code == 401:
        raise RuntimeError(
            "NewsData.io 401 Unauthorized: Check your API key at https://newsdata.io - "
            "ensure it's correct, the account is verified, and the key has no extra spaces."
        )
    r.raise_for_status()
    data = r.json()

    if data.get("status") != "success":
        raise RuntimeError(
            f"NewsData.io API error: {data.get('message', data.get('results', 'Unknown'))}"
        )

    results = data.get("results", [])
    return results[:max_results]


def fetch_articles_randomized(
    *,
    topic: str | None = None,
    language: str | None = "en",
    max_results: int = 10,
    rng: random.Random | None = None,
) -> tuple[list[dict], dict]:
    """
    Random tech-focused fetch: NewsData categories always include ``technology`` plus 0–2
    tech-adjacent buckets (science / business / top), an optional tech sub-field query,
    then shuffle results.

    Returns:
        (articles, meta) where meta includes chosen category list and q for logging/UI.
    """
    rng = rng or random.Random()
    chosen_cats = ["technology"]
    extras = list(NEWSDATA_TECH_CATEGORY_EXTRAS)
    n_extra = rng.randint(0, min(2, len(extras)))
    if n_extra:
        chosen_cats.extend(rng.sample(extras, k=n_extra))
    category_param = ",".join(chosen_cats)

    pool = list(NEWSDATA_TECH_QUERIES)
    if topic and topic.strip():
        t = topic.strip().lower()
        if t not in {"technology", "tech"}:
            pool.extend([topic.strip(), None])
    q_choice = rng.choice(pool)
    if q_choice is None and topic and topic.strip() and rng.random() < 0.3:
        q_choice = topic.strip()

    articles = fetch_articles(
        q=q_choice,
        language=language,
        category=category_param,
        max_results=max_results,
    )
    articles = list(articles)
    rng.shuffle(articles)
    meta = {
        "categories": chosen_cats,
        "category_param": category_param,
        "q": q_choice,
        "tech_focus": True,
    }
    return articles[:max_results], meta


def newsdata_to_unified_sources(
    articles: list[dict],
    topic: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Convert NewsData.io API response to unified source schema."""
    sources = []
    for i, art in enumerate(articles):
        link = art.get("link", "")
        if not link:
            continue
        snippet = art.get("description") or art.get("content") or art.get("title", "")
        pub = art.get("pubDate", "")
        src = unified_source(
            source_id=make_source_id("nd", link),
            title=art.get("title", "Untitled"),
            url=link,
            publisher=art.get("source_name", "Unknown"),
            published_at=normalize_published_at(pub),
            snippet=snippet,
            source_type="newsdata",
            topic=topic,
            category=category or (
                (art.get("category") or [None])[0]
                if isinstance(art.get("category"), list)
                else art.get("category")
            ),
        )
        sources.append(src)
    return sources


def articles_to_bundle_sources(articles: list[dict]) -> list[dict]:
    """
    Convert NewsData.io articles to bundle source format.

    Bundle source format: {source_id, url, publisher, published_at, snippet}
    """
    sources = []
    for i, art in enumerate(articles):
        snippet = art.get("description") or art.get("content") or ""
        if not snippet and art.get("content"):
            snippet = art["content"]
        if len(snippet) > 800:
            snippet = snippet[:800].rsplit(" ", 1)[0] + "..."

        pub_date = art.get("pubDate", "")
        if pub_date and " " in pub_date:
            try:
                dt = datetime.strptime(pub_date, "%Y-%m-%d %H:%M:%S")
                pub_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        sources.append(
            {
                "source_id": art.get("article_id", f"nd_{i}"),
                "url": art.get("link", ""),
                "publisher": art.get("source_name", "Unknown"),
                "published_at": pub_date,
                "snippet": snippet or art.get("title", ""),
            }
        )
    return sources
