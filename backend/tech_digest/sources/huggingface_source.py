"""
Tier 2: Hugging Face. Two endpoints, both unauthenticated:
- /api/daily_papers   -> curated daily research papers (replaces Papers with Code)
- /api/models?sort=trending -> trending model releases
"""
from datetime import datetime
import requests

from ..schema import NewsItem
from .. import config

PAPERS_URL = "https://huggingface.co/api/daily_papers"
MODELS_URL = "https://huggingface.co/api/models?sort=trendingScore&limit=20"


def fetch_huggingface() -> list[NewsItem]:
    items = []

    try:
        papers = requests.get(PAPERS_URL, timeout=10).json()
        for p in papers:
            paper = p.get("paper", {})
            items.append(NewsItem(
                title=paper.get("title", "").strip(),
                url=f"https://huggingface.co/papers/{paper.get('id', '')}",
                source="Hugging Face Papers",
                tier=2,
                category="research",
                published_at=_parse_date(p.get("publishedAt")),
                engagement_raw=p.get("paper", {}).get("upvotes", 0),
                summary=paper.get("summary", "")[:500],
            ))
    except Exception as e:
        print(f"[huggingface] daily_papers failed -- {e}")

    try:
        models = requests.get(MODELS_URL, timeout=10).json()
        if isinstance(models, dict) and "error" in models:
            print(f"[huggingface] trending models API error: {models['error']}")
        elif isinstance(models, list):
            for m in models:
                items.append(NewsItem(
                    title=m.get("id", "").strip(),
                    url=f"https://huggingface.co/{m.get('id', '')}",
                    source="Hugging Face Models",
                    tier=2,
                    category="launch",
                    published_at=_parse_date(m.get("lastModified") or m.get("createdAt")),
                    engagement_raw=m.get("likes", 0),
                    summary="",
                ))
        else:
            print(f"[huggingface] trending models returned unexpected format: {type(models)}")
    except Exception as e:
        print(f"[huggingface] trending models failed -- {e}")

    return items


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
