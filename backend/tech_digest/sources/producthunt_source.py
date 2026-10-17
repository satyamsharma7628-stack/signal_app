"""
Tier 3: Product Hunt, via their GraphQL API v2.
Needs a developer token: create an app at https://api.producthunt.com/v2/oauth/applications,
generate a "developer token" (no OAuth flow needed for read-only personal use).

Set PRODUCTHUNT_TOKEN as an env var before running.
"""
from datetime import datetime
import requests

from ..schema import NewsItem
from .. import config

GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

QUERY = """
{
  posts(first: 20, order: VOTES) {
    edges {
      node {
        name
        tagline
        url
        votesCount
        createdAt
      }
    }
  }
}
"""


def fetch_producthunt() -> list[NewsItem]:
    items = []
    if not config.PRODUCTHUNT_TOKEN:
        print("[producthunt] skipped -- PRODUCTHUNT_TOKEN not set")
        return items

    headers = {
        "Authorization": f"Bearer {config.PRODUCTHUNT_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(GRAPHQL_URL, json={"query": QUERY}, headers=headers, timeout=10)
        resp.raise_for_status()
        edges = resp.json()["data"]["posts"]["edges"]
        for edge in edges:
            node = edge["node"]
            items.append(NewsItem(
                title=node["name"].strip(),
                url=node["url"],
                source="Product Hunt",
                tier=3,
                category="launch",
                published_at=_parse_date(node.get("createdAt")),
                engagement_raw=node.get("votesCount", 0),
                summary=node.get("tagline", "")[:500],
            ))
    except Exception as e:
        print(f"[producthunt] failed -- {e}")
    return items


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
