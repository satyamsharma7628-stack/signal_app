"""
Tier 2: Lobsters, via its public read-only JSON API (no key needed).
Smaller and more curated than HN -- skews toward programming, systems,
and security, which is a useful counterweight to HN's broader mix.
"""
from datetime import datetime
import requests

from ..schema import NewsItem
from .. import config

URL = "https://lobste.rs/hottest.json"
MAX_RESULTS = 25


def fetch_lobsters() -> list[NewsItem]:
    items = []
    try:
        resp = requests.get(URL, timeout=10)
        resp.raise_for_status()
        stories = resp.json()[:MAX_RESULTS]
        for story in stories:
            items.append(NewsItem(
                title=story.get("title", "").strip(),
                url=story.get("url") or story.get("comments_url", ""),
                source="Lobsters",
                tier=2,
                category="discussion",
                published_at=_parse_date(story.get("created_at")),
                engagement_raw=story.get("score", 0),
                summary=", ".join(story.get("tags", [])),
            ))
    except Exception as e:
        print(f"[lobsters] failed -- {e}")
    return items


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None
