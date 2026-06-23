"""
Source weights (used later by the scoring stage, defined here so they live
next to the source list) and credential loading from environment variables.

Nothing here makes network calls.
"""
import os

# Tier 1 -- RSS, no auth
RSS_FEEDS = {
    "TechCrunch":          ("https://techcrunch.com/feed/", 0.8),
    "The Verge":           ("https://www.theverge.com/rss/index.xml", 0.7),
    "Ars Technica":        ("https://feeds.arstechnica.com/arstechnica/index", 0.85),
    "MIT Technology Review": ("https://www.technologyreview.com/feed/", 0.85),
    "Krebs on Security":   ("https://krebsonsecurity.com/feed/", 0.9),
    "The Hacker News":     ("https://feeds.feedburner.com/TheHackersNews", 0.9),
    "Stack Overflow Blog": ("https://stackoverflow.blog/feed/", 0.6),
    "Wired":               ("https://www.wired.com/feed/rss", 0.7),
    "Engadget":            ("https://www.engadget.com/rss.xml", 0.65),
    "ZDNet":               ("https://www.zdnet.com/news/rss.xml", 0.6),
    "InfoQ":               ("https://www.infoq.com/feed/", 0.7),
    "Smashing Magazine":   ("https://www.smashingmagazine.com/feed/", 0.6),
}

# Tier 2 -- free APIs, no key needed (HN, arXiv, Lobsters, Dev.to) or free signup (Reddit)
HN_WEIGHT = 1.0
ARXIV_WEIGHT = 0.7
ARXIV_CATEGORIES = ["cs.AI", "cs.CR", "cs.LG", "cs.CV"]  # AI, security, ML, vision -- matches your interests
ARXIV_MAX_RESULTS = 25

REDDIT_WEIGHT = 0.75
SUBREDDITS = ["programming", "MachineLearning", "netsec", "gamedev", "startups",
              "SideProject", "webdev", "artificial"]
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = "tech_digest_bot/0.1 (personal use)"

HF_WEIGHT = 0.7
LOBSTERS_WEIGHT = 0.75
INDIEHACKERS_WEIGHT = 0.7
DEVTO_WEIGHT = 0.65

GITHUB_WEIGHT = 0.7
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional, raises rate limit 60->5000/hr

# Tier 3 -- needs a dev token
PRODUCTHUNT_WEIGHT = 0.7
PRODUCTHUNT_TOKEN = os.environ.get("PRODUCTHUNT_TOKEN")
