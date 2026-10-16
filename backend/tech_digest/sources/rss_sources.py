"""
Tier 1: plain RSS. All 7 sources go through this one function since they're
structurally identical -- title, link, published date, summary.
"""
from datetime import datetime
from time import mktime
import feedparser

from ..schema import NewsItem
from .. import config


def fetch_rss() -> list[NewsItem]:
    items = []
    for source_name, (url, _weight) in config.RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                print(f"[rss] {source_name}: failed to parse ({feed.bozo_exception})")
                continue
            for entry in feed.entries:
                published = None
                if getattr(entry, "published_parsed", None):
                    published = datetime.fromtimestamp(mktime(entry.published_parsed))
                items.append(NewsItem(
                    title=entry.get("title", "").strip(),
                    url=entry.get("link", ""),
                    source=source_name,
                    tier=1,
                    category="news",
                    published_at=published,
                    engagement_raw=0.0,  # RSS has no engagement signal
                    summary=entry.get("summary", "")[:500],
                ))
        except Exception as e:
            print(f"[rss] {source_name}: error -- {e}")
    return items
