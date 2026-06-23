"""
Tier 2: Dev.to, via its public API (no key needed). Pulls top articles
from the last week. Dev.to skews strongly toward "I built X, here's how"
posts, so this feeds the builder-ideas pool as much as the general feed.
"""
from datetime import datetime
import requests

URL = "https://dev.to/api/articles"
PARAMS = {"top": 7, "per_page": 25}  # top articles from the last 7 days

from ..schema import NewsItem


def fetch_devto() -> list[NewsItem]:
    items = []
    try:
        resp = requests.get(URL, params=PARAMS, timeout=10)
        resp.raise_for_status()
        articles = resp.json()
        for a in articles:
            items.append(NewsItem(
                title=a.get("title", "").strip(),
                url=a.get("url", ""),
                source="Dev.to",
                tier=2,
                category="discussion",
                published_at=_parse_date(a.get("published_at")),
                engagement_raw=a.get("positive_reactions_count", 0),
                summary=(a.get("description") or "")[:500],
            ))
    except Exception as e:
        print(f"[devto] failed -- {e}")
    return items


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
