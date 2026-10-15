"""
Tier 2: GitHub "trending", approximated via the public Search API since
GitHub has no official trending endpoint. We search for repos created in
the last N days, sorted by stars -- this is the same approach most
unofficial "trending" tools use.

Works without auth (60 req/hour limit). Set GITHUB_TOKEN to raise that to
5000 req/hour if this runs on a schedule.
"""
from datetime import datetime, timedelta
import requests

from ..schema import NewsItem
from .. import config

SEARCH_URL = "https://api.github.com/search/repositories"
LOOKBACK_DAYS = 7
MAX_RESULTS = 25


def fetch_github_trending() -> list[NewsItem]:
    items = []
    since = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    params = {
        "q": f"created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": MAX_RESULTS,
    }
    try:
        resp = requests.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        if resp.status_code == 403:
            print("[github] rate limited -- set GITHUB_TOKEN to raise the limit")
            return items
        resp.raise_for_status()
        repos = resp.json().get("items", [])
        for repo in repos:
            items.append(NewsItem(
                title=repo.get("full_name", "").strip(),
                url=repo.get("html_url", ""),
                source="GitHub Trending",
                tier=2,
                category="launch",
                published_at=_parse_date(repo.get("created_at")),
                engagement_raw=repo.get("stargazers_count", 0),
                summary=(repo.get("description") or "")[:500],
            ))
    except Exception as e:
        print(f"[github] failed -- {e}")
    return items


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
