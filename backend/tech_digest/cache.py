"""
AI summary cache. Backed by Supabase (the summary_cache table), not local
SQLite -- a free Render web service wipes local disk on every sleep/
restart, so a SQLite file here would lose every cached summary
unpredictably. Same get/save function names as before so callers
(main.py) didn't need to change.
"""
from datetime import datetime, timezone

from . import db


def get_cached_summary(url: str) -> str | None:
    client = db.get_client()
    result = (
        client.table("summary_cache")
        .select("summary")
        .eq("url", url)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["summary"]
    return None


def save_summary_to_cache(url: str, summary: str):
    client = db.get_client()
    client.table("summary_cache").upsert(
        {
            "url": url,
            "summary": summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="url",
    ).execute()
