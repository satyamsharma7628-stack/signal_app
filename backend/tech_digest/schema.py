"""
Common schema every fetcher normalizes into.
Keeping this dumb on purpose -- no scoring/dedup logic lives here,
that's a separate stage that consumes lists of NewsItem.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class NewsItem:
    title: str
    url: str
    source: str            # e.g. "TechCrunch", "Hacker News", "r/programming"
    tier: int               # 1, 2, or 3 -- trust/integration tier from the source plan
    category: str            # "news" | "discussion" | "research" | "launch" | "idea"
    published_at: Optional[datetime] = None
    engagement_raw: float = 0.0   # points/upvotes/stars/likes -- 0 if source has none
    summary: str = ""
    is_builder_idea: bool = False   # True for "Show HN", r/startups builds, indie launches, etc.
    stack_tags: list[str] = field(default_factory=list)  # extracted tech mentions, e.g. ["Next.js", "Postgres"]
    dedup_key: str = ""     # normalized title used to collapse cross-source duplicates

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        return d
