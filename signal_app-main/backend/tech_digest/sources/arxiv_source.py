"""
Tier 2: arXiv, via the official Atom API (no key).
Pulls recent submissions across the categories in config.ARXIV_CATEGORIES.
"""
from datetime import datetime
import feedparser
import urllib.parse
import requests

from ..schema import NewsItem
from .. import config

BASE = "http://export.arxiv.org/api/query"


def fetch_arxiv() -> list[NewsItem]:
    items = []
    cat_query = "+OR+".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES)
    query = (
        f"{BASE}?search_query={cat_query}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={config.ARXIV_MAX_RESULTS}"
    )
    try:
        response = requests.get(query, timeout=10)
        feed = feedparser.parse(response.text)
        for entry in feed.entries:
            published = None
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6])
            items.append(NewsItem(
                title=entry.get("title", "").strip().replace("\n", " "),
                url=entry.get("link", ""),
                source="arXiv",
                tier=2,
                category="research",
                published_at=published,
                engagement_raw=0.0,  # arXiv has no engagement signal
                summary=entry.get("summary", "")[:500].replace("\n", " "),
            ))
    except Exception as e:
        print(f"[arxiv] failed -- {e}")
    return items
