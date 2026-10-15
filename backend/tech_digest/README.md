# tech_digest — data layer

Fetches and normalizes items from 15 sources into one `NewsItem` schema,
dedups cross-posted stories (both within a single run and against what's
already saved from earlier runs), and tags "builder idea" content (Show HN,
Product Hunt, indie launches, new repos).

This package is the data layer only. It's consumed by `../main.py` (the
FastAPI backend) and saves to Supabase via `db.py` — see the top-level
`README.md` for the full architecture and deployment steps. This file
covers just what's in here.

## Setup

```bash
pip install -r ../requirements.txt
cp ../.env.example ../.env   # then fill in the keys you have
```

Required: `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (use the service_role
/ secret key, not anon/publishable — this runs server-side only).

Everything else is optional (sources work without them, just skip and print a warning):

```bash
# Reddit -- register a "script" app at https://www.reddit.com/prefs/apps (2 min)
REDDIT_CLIENT_ID="..."
REDDIT_CLIENT_SECRET="..."

# Product Hunt -- create a dev token at https://api.producthunt.com/v2/oauth/applications
PRODUCTHUNT_TOKEN="..."

# GitHub -- optional, raises the search API rate limit from 60/hr to 5000/hr
GITHUB_TOKEN="..."

# Gemini -- powers the on-demand article summaries in the UI
GEMINI_API_KEY="..."
```

**Never commit `.env`.** It's already in `.gitignore`. If a key ever ends up
somewhere it shouldn't (a chat, a repo, a screenshot), rotate it immediately.

## Run

```bash
python -m tech_digest.fetch_all     # one-off fetch -> saves to Supabase
```

This also writes a local debug JSON snapshot to `output/` purely so you
can eyeball what was fetched by hand — the running app never reads that
file; Supabase is the real source of truth. Set
`WRITE_LOCAL_JSON_SNAPSHOT=0` to skip it.

## What's covered

| Tier | Source | Auth needed |
|---|---|---|
| 1 | TechCrunch, The Verge, Ars Technica, MIT Tech Review, Krebs on Security, The Hacker News, Stack Overflow Blog, Wired, Engadget, ZDNet, InfoQ, Smashing Magazine | none (RSS) |
| 2 | Hacker News | none |
| 2 | arXiv (cs.AI, cs.CR, cs.LG, cs.CV) | none |
| 2 | Reddit (r/programming, r/MachineLearning, r/netsec, r/gamedev, r/startups, r/SideProject, r/webdev, r/artificial) | client_id + secret |
| 2 | Hugging Face (daily papers + trending models) | none |
| 2 | GitHub Trending (via Search API — no official trending endpoint exists) | none (optional token raises rate limit) |
| 2 | Lobsters | none |
| 2 | IndieHackers (via RSS — no public API) | none |
| 2 | Dev.to | none |
| 3 | Product Hunt | dev token |

Edit `config.py` to change subreddits, arXiv categories, or per-source weights.

## Builder ideas

A dedicated view filters down to "someone shipped something and said what
they used": Show HN posts, Product Hunt launches, r/SideProject and
r/startups build posts, new GitHub repos, IndieHackers posts, and new
Hugging Face model releases. Each item gets a lightweight extracted stack
tag list (e.g. `Next.js`, `Postgres`, `Rust`) pulled from the title/summary
via keyword matching — see `enrich.py`. This is intentionally simple
keyword matching, not ML, so it's fast, free, and easy to extend (add to
`_STACK_KEYWORDS`).

User-submitted idea comparison (novelty / success-likelihood scoring
against this corpus) is deliberately **not** built yet — flagged as a
next stage once the data layer below it is solid.

## Dedup

`enrich.py` has two passes:

1. **Within a run** (`dedup_items`): collapses items that are the same
   story cross-posted to multiple sources in the same fetch (e.g. a launch
   that hits HN, Product Hunt, and r/startups same-day). Merges on a fuzzy
   normalized-title match, keeps the highest-priority source's copy, sums
   engagement across the duplicates, and tags the summary with where else
   it appeared.
2. **Across runs** (`dedup_against_existing`): since each item is now
   upserted into Supabase by URL, the same story re-appearing under a
   *different* URL in a later run wouldn't be caught by the upsert alone
   (different URL = different primary key). This pass checks new items
   against titles already saved from earlier runs and skips re-inserting
   a same-story duplicate.

Both passes leave titles under 3 meaningful words alone, since they're too
generic to dedup safely (e.g. two unrelated "v2.0" posts won't get merged).

## Note

The four newer sources (GitHub, Lobsters, IndieHackers, Dev.to) and the
Supabase integration were built and compile/logic-checked in a sandbox
without outbound network access to these domains — verified via synthetic
data and dry-run logic tests, not live API calls. Run `fetch_all` on your
machine and check the per-source item counts it prints; some feed URLs
(especially Verge/Ars Technica) occasionally change and may need a quick fix.

