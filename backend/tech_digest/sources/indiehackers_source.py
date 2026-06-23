"""
Tier 2: IndieHackers, via RSS (no public API exists). Every post on this
forum is implicitly a "builder idea" -- people sharing what they made,
revenue numbers, stack choices -- so unlike other sources, every item here
gets is_builder_idea=True straight from the fetcher rather than waiting on
the keyword heuristics in enrich.py.
"""
from datetime import datetime
from time import mktime
import feedparser

from ..schema import NewsItem

FEED_URL = "https://www.indiehackers.com/feed.xml"


def fetch_indiehackers() -> list[NewsItem]:
    items = []
    try:
        feed = feedparser.parse(FEED_URL)
        if feed.bozo and not feed.entries:
            print(f"[indiehackers] failed to parse ({feed.bozo_exception})")
            return items
        for entry in feed.entries:
            published = None
            if getattr(entry, "published_parsed", None):
                published = datetime.fromtimestamp(mktime(entry.published_parsed))
            items.append(NewsItem(
                title=entry.get("title", "").strip(),
                url=entry.get("link", ""),
                source="IndieHackers",
                tier=2,
                category="idea",
                published_at=published,
                engagement_raw=0.0,  # feed has no engagement signal
                summary=entry.get("summary", "")[:500],
                is_builder_idea=True,
            ))
    except Exception as e:
        print(f"[indiehackers] error -- {e}")
    return items
