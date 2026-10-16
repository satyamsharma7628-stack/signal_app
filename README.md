# Signal — tech digest

A self-updating feed of tech news, research, and "what people are building"
across 15 sources, with dedup and builder-idea tagging. Built as a real
web app (FastAPI + React) instead of Streamlit, so it's fast and responsive
on mobile.

## Architecture

```
GitHub Actions (cron, every ~15 min)
        |
        v  POST /api/refresh
FastAPI backend (Render, free tier)
        |
        v  fetches 15 sources, dedups, tags builder ideas
Supabase Postgres (free tier)  <-- single source of truth
        ^
        |  GET /api/items, /api/status
        |
React frontend (Cloudflare Pages, free)  <-- what you open on your phone
```

**Why this shape, specifically:**
- Render's free tier wipes local disk on every sleep/restart, so the
  fetched data lives in Supabase, not a JSON file on the backend's
  filesystem. See `backend/tech_digest/db.py` -- it's the only file that
  talks to Supabase, so swapping storage later only touches one place.
- The backend sleeps after ~15 min idle and takes 10-30s to wake on the
  next request. The GitHub Actions cron job hits `/api/refresh` every 15
  min specifically to keep data fresh *even if nobody opens the app* --
  but the first load after a quiet stretch can still be slow. The frontend
  shows a "waking up" message instead of looking broken (`src/api.js`,
  `fetchWithRetry`).
- Dedup runs twice: once within a single fetch (catches the same story
  hitting HN + Product Hunt + Reddit in one run) and once against what's
  already in the database (catches the same story re-appearing under a new
  URL in a *later* run). See `enrich.py`.

## Setup

### 1. Supabase (data store)
1. Create a free project at supabase.com.
2. Open the SQL Editor and run `supabase_schema.sql` from this repo.
3. Settings → API: copy the Project URL and the `service_role` (or
   `secret`) key -- **not** the anon/publishable key.

### 2. Backend (Render)
1. Push this repo to GitHub.
2. Render Dashboard → New → Blueprint → connect the repo. It reads
   `render.yaml` and creates the service.
3. When prompted, fill in: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and
   whichever of `GEMINI_API_KEY` / `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`
   / `PRODUCTHUNT_TOKEN` / `GITHUB_TOKEN` you have. All are optional except
   the two Supabase ones.
4. Once deployed, copy the service's `.onrender.com` URL.

### 3. Frontend (Cloudflare Pages)
1. Cloudflare dashboard → Workers & Pages → Create → Pages → connect repo.
2. Build settings: root directory `frontend`, build command `npm run build`,
   output directory `dist`.
3. Add a build environment variable `VITE_API_BASE` set to your Render
   backend URL from step 2.4.
4. Once deployed, go back to `backend/main.py` and add the Cloudflare Pages
   URL to `FRONTEND_ORIGINS`, then redeploy the backend -- without this,
   the browser will block requests from your frontend to your backend
   (CORS).

### 4. GitHub Actions (keeps it fresh automatically)
1. Repo Settings → Secrets and variables → Actions → New repository secret:
   `BACKEND_URL` = your Render backend URL (no trailing slash).
2. The workflow in `.github/workflows/refresh.yml` runs automatically every
   15 minutes once this secret exists. You can also trigger it manually
   from the Actions tab to test it immediately after setup.

## Local development

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL + SUPABASE_SERVICE_KEY at minimum
uvicorn main:app --reload

# Fetch once by hand to populate Supabase with real data
python -m tech_digest.fetch_all

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE=http://localhost:8000
npm run dev
```

## What's covered

15 sources across 3 tiers (RSS feeds, free APIs, and Product Hunt's dev
token tier) -- see `backend/tech_digest/README.md` for the full list and
the builder-ideas / dedup design notes, which carry over unchanged from
the data layer.

## Not built yet

User-submitted idea comparison (novelty / success-likelihood scoring
against this corpus) is deliberately deferred -- it needs an on-demand LLM
call, which this architecture supports (the backend is live, not static),
but it's a separate feature to design and test on its own.
