"""
Tier 2: Hacker News, via the official Firebase API (no key).
Pulls top story IDs, then fetches each story's details.
Capped at TOP_N to avoid hammering the API on every run.
"""
from datetime import datetime
import requests

from ..schema import NewsItem
from .. import config

BASE = "https://hacker-news.firebaseio.com/v0"
TOP_N = 30


def fetch_hn() -> list[NewsItem]:
    items = []
    try:
        top_ids = requests.get(f"{BASE}/topstories.json", timeout=10).json()[:TOP_N]
    except Exception as e:
        print(f"[hn] failed to fetch top stories -- {e}")
        return items

    for story_id in top_ids:
        try:
            story = requests.get(f"{BASE}/item/{story_id}.json", timeout=10).json()
            if not story or story.get("type") != "story":
                continue
            items.append(NewsItem(
                title=story.get("title", "").strip(),
                url=story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                source="Hacker News",
                tier=2,
                category="discussion",
                published_at=datetime.fromtimestamp(story["time"]) if "time" in story else None,
                engagement_raw=story.get("score", 0),
                summary="",  # HN doesn't give article text, just title + link
            ))
        except Exception as e:
            print(f"[hn] item {story_id} failed -- {e}")
    return items
