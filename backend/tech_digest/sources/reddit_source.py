"""
Tier 2: Reddit, via PRAW in read-only mode (client_id + client_secret only,
no username/password needed). Get credentials by registering a "script" app
at https://www.reddit.com/prefs/apps -- takes 2 minutes.

Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET as env vars before running.
"""
from datetime import datetime
import praw

from ..schema import NewsItem
from .. import config

POSTS_PER_SUB = 15


def fetch_reddit() -> list[NewsItem]:
    items = []
    if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
        print("[reddit] skipped -- REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
        return items

    try:
        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
    except Exception as e:
        print(f"[reddit] auth failed -- {e}")
        return items

    for sub in config.SUBREDDITS:
        try:
            for post in reddit.subreddit(sub).hot(limit=POSTS_PER_SUB):
                if post.stickied:
                    continue
                items.append(NewsItem(
                    title=post.title.strip(),
                    url=post.url if not post.is_self else f"https://reddit.com{post.permalink}",
                    source=f"r/{sub}",
                    tier=2,
                    category="discussion",
                    published_at=datetime.fromtimestamp(post.created_utc),
                    engagement_raw=post.score,
                    summary=(post.selftext or "")[:500],
                ))
        except Exception as e:
            print(f"[reddit] r/{sub} failed -- {e}")
    return items
