"""
Runs every Tier 1-3 fetcher and dumps the normalized, un-scored, un-deduped
output to a timestamped JSON file under output/.

Deliberately does NOT score or dedup here -- that's the next stage, and it
needs to be designed against real sample output, not guessed at blind.
Run this, eyeball the JSON, then we build scoring on top of it.
"""
"""
Runs every Tier 1-3 fetcher, enriches (dedup + builder-idea tagging), and
saves the result to Supabase -- the single source of truth the FastAPI
backend reads from. Also writes a local JSON snapshot purely for debugging
(e.g. running this script by hand to eyeball output); the app itself never
reads that file.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from .sources.rss_sources import fetch_rss
from .sources.hn import fetch_hn
from .sources.arxiv_source import fetch_arxiv
from .sources.reddit_source import fetch_reddit
from .sources.huggingface_source import fetch_huggingface
from .sources.producthunt_source import fetch_producthunt
from .sources.github_trending import fetch_github_trending
from .sources.lobsters_source import fetch_lobsters
from .sources.indiehackers_source import fetch_indiehackers
from .sources.devto_source import fetch_devto
from .enrich import enrich, dedup_against_existing
from . import db

FETCHERS = [
    ("RSS (Tier 1)", fetch_rss),
    ("Hacker News (Tier 2)", fetch_hn),
    ("arXiv (Tier 2)", fetch_arxiv),
    ("Reddit (Tier 2)", fetch_reddit),
    ("Hugging Face (Tier 2)", fetch_huggingface),
    ("GitHub Trending (Tier 2)", fetch_github_trending),
    ("Lobsters (Tier 2)", fetch_lobsters),
    ("IndieHackers (Tier 2)", fetch_indiehackers),
    ("Dev.to (Tier 2)", fetch_devto),
    ("Product Hunt (Tier 3)", fetch_producthunt),
]


def run():
    all_items = []
    for label, fn in FETCHERS:
        try:
            items = fn()
        except Exception as e:
            print(f"{label}: fetcher crashed -- {e}")
            items = []
        print(f"{label}: {len(items)} items")
        all_items.extend(items)

    before = len(all_items)
    all_items = enrich(all_items)

    # Cross-run dedup: catch the same story re-appearing under a new URL
    # in a later fetch, which a fresh-per-run dedup pass alone can't see.
    try:
        existing_rows = db.load_items()
    except Exception as e:
        print(f"(could not load existing rows for cross-run dedup: {e})")
        existing_rows = []
    if existing_rows:
        before_cross = len(all_items)
        all_items = dedup_against_existing(all_items, existing_rows)
        if before_cross != len(all_items):
            print(f"Cross-run dedup: dropped {before_cross - len(all_items)} items already seen in earlier runs")

    idea_count = sum(1 for i in all_items if i.is_builder_idea)
    print(f"\nEnriched: {before} -> {len(all_items)} after dedup, {idea_count} tagged as builder ideas")

    saved = db.save_items(all_items)
    print(f"Saved {saved} rows to Supabase")

    # Optional local debug snapshot -- skipped automatically if the
    # filesystem write fails (e.g. read-only deploy environment), since
    # it's a nice-to-have, not the real persistence layer anymore.
    if os.environ.get("WRITE_LOCAL_JSON_SNAPSHOT", "1") == "1":
        try:
            out_dir = Path(__file__).parent / "output"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(out_path, "w") as f:
                json.dump([item.to_dict() for item in all_items], f, indent=2)
            print(f"Local debug snapshot -> {out_path}")
        except Exception as e:
            print(f"(skipped local snapshot: {e})")

    print(f"Total: {len(all_items)} items")
    return all_items


if __name__ == "__main__":
    run()
