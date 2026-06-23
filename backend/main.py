"""
FastAPI backend for Signal. Wraps the existing fetch/enrich/summarize layer
from tech_digest/ behind a small HTTP API so a React frontend (and a
GitHub Actions cron job) can talk to it.

Data lives in Supabase, not local disk -- Render's free tier wipes local
filesystem changes on every sleep/restart, so the JSON-file approach used
during local prototyping doesn't survive there. tech_digest/db.py is the
only module that talks to Supabase; everything else is unchanged.

Endpoints:
  GET  /api/items     -> latest enriched items (the feed)
  GET  /api/status     -> last fetch time, per-source counts, in-progress flag
  POST /api/refresh     -> triggers a fetch in the background (used by cron)
  GET  /api/summary     -> on-demand AI summary for one item (cached)
"""
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tech_digest.fetch_all import run as run_fetch
from tech_digest.cache import get_cached_summary, save_summary_to_cache
from tech_digest.summarizer import summarize_article
from tech_digest import db

app = FastAPI(title="Signal API")

# Locked down to the deployed frontend origin(s) -- update FRONTEND_ORIGINS
# with your real Cloudflare Pages URL (and localhost for local dev) once
# you have it. Using "*" here would let any website call this API on your
# behalf, which matters once this is public on the internet.
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    # "https://your-project.pages.dev",  # <- add your real deployed URL here
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Simple in-process state. Fine for a single small Render instance; would
# need to move to a real lock/queue (e.g. Redis) if this ever ran with
# multiple backend workers. Separate from the data layer -- this is just
# "is a fetch running right now", which doesn't need to survive a restart.
_state = {"fetching": False, "last_error": None, "last_fetch_started_at": None}


def _run_fetch_job():
    _state["fetching"] = True
    _state["last_error"] = None
    _state["last_fetch_started_at"] = time.time()
    try:
        run_fetch()
    except Exception as e:
        _state["last_error"] = str(e)
        print(f"[refresh] fetch job failed: {e}")
    finally:
        _state["fetching"] = False


@app.get("/api/status")
def get_status():
    try:
        items = db.load_items()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reach database: {e}")

    counts: dict[str, int] = {}
    latest_updated = None
    for item in items:
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        updated = item.get("updated_at")
        if updated and (latest_updated is None or updated > latest_updated):
            latest_updated = updated

    return {
        "last_fetch_at": latest_updated,
        "fetching": _state["fetching"],
        "source_counts": counts,
        "total_items": len(items),
        "last_error": _state["last_error"],
    }


@app.get("/api/items")
def get_items(
    builder_ideas_only: bool = False,
    source: Optional[str] = None,
    category: Optional[str] = None,
    stack: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query("newest", pattern="^(newest|oldest|engagement)$"),
):
    try:
        items = db.load_items()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not reach database: {e}")

    if builder_ideas_only:
        items = [i for i in items if i.get("is_builder_idea")]
    if source:
        items = [i for i in items if i["source"] == source]
    if category:
        items = [i for i in items if i["category"] == category]
    if stack:
        items = [i for i in items if stack in (i.get("stack_tags") or [])]
    if search:
        q = search.lower()
        items = [
            i for i in items
            if q in i["title"].lower()
            or q in (i.get("summary") or "").lower()
            or any(q in t.lower() for t in (i.get("stack_tags") or []))
        ]

    # The DB query already orders by published_at desc; only re-sort here
    # if a different order was requested.
    if sort == "oldest":
        items.sort(key=lambda i: i.get("published_at") or "")
    elif sort == "engagement":
        items.sort(key=lambda i: i.get("engagement_raw") or 0, reverse=True)

    return {"items": items, "total": len(items)}


@app.post("/api/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    # Returns immediately; the actual fetch runs in the background so the
    # cron job's HTTP request doesn't time out waiting for ~10 sources to
    # finish. Poll /api/status afterward to see when it's done.
    if _state["fetching"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_fetch_job)
    return {"status": "started"}


class SummaryRequest(BaseModel):
    url: str
    title: str
    category: str
    existing_summary: str = ""


@app.post("/api/summary")
def get_summary(req: SummaryRequest):
    cached = get_cached_summary(req.url)
    if cached:
        return {"summary": cached, "cached": True}
    try:
        generated = summarize_article(
            url=req.url,
            title=req.title,
            category=req.category,
            existing_summary=req.existing_summary,
            api_key=os.environ.get("GEMINI_API_KEY"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {e}")
    save_summary_to_cache(req.url, generated)
    return {"summary": generated, "cached": False}


@app.get("/api/health")
def health():
    # Cheap endpoint for the cron job to hit first if you ever want a
    # pure "wake up" ping separate from triggering a real fetch.
    return {"ok": True}

