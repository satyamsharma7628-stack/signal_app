"""
FastAPI backend for Signal.
Supports 3 account tiers: FREE, PRO, and ADMIN (plus SUSPENDED access revocation).
Endpoints:
  GET    /api/items               -> latest enriched items (the feed)
  GET    /api/status              -> last fetch time, per-source counts, in-progress flag
  POST   /api/refresh             -> triggers a fetch in the background (used by cron)
  POST   /api/summary             -> on-demand 50-word AI summary for one item (cached)
  POST   /api/ideate              -> Idea Network & 4-point Brainstorm blueprint
  POST   /api/chat                -> Multi-turn AI Builder Chat
  GET    /api/me                  -> authenticated user's profile & saved items
  PUT    /api/me/preferences      -> save user's niche departments & preferred sources
  PUT    /api/me/newsletter       -> toggle Daily Top 10 & Weekly AI Playbook subscriptions
  GET    /api/me/saved            -> list user's saved items & custom notes
  POST   /api/me/saved            -> save or edit a bookmarked item / custom note
  DELETE /api/me/saved            -> remove a bookmarked item
  POST   /api/admin/claim         -> elevate account to ADMIN via ADMIN_SECRET or switch tier for testing
  GET    /api/admin/users         -> [ADMIN] list all user accounts & tiers
  PUT    /api/admin/users/tier    -> [ADMIN] grant FREE / PRO / ADMIN or SUSPEND an account
  DELETE /api/admin/items         -> [ADMIN] take down / delete a published feed item
  GET    /api/newsletter/preview  -> preview Daily Top 10 or Weekly AI Playbook (cached)
  POST   /api/newsletter/send-test-> send a test newsletter to the logged-in user's email
  POST   /api/newsletter/dispatch -> cron endpoint to send daily/weekly newsletter to subscribers
"""
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from tech_digest.fetch_all import run as run_fetch
from tech_digest.cache import get_cached_summary, save_summary_to_cache
from tech_digest.summarizer import (
    summarize_article,
    find_nearby_connected_items,
    generate_idea_network_blueprint,
    chat_with_builder_ai,
)
from tech_digest import db, newsletter

app = FastAPI(title="Signal API")

FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://signal-app-asd.pages.dev",
    "https://signal-app-asd.pages.dev/",
]
if os.environ.get("FRONTEND_ORIGIN"):
    FRONTEND_ORIGINS.append(os.environ["FRONTEND_ORIGIN"].rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")
    token = authorization.split(" ", 1)[1].strip()
    user_info = db.verify_user_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired login session.")
    profile = db.get_or_create_user_profile(user_info)
    if profile.get("subscription_tier") == "suspended":
        raise HTTPException(
            status_code=403,
            detail="Your account access has been removed/suspended by an administrator.",
        )
    user_info["profile"] = profile
    return user_info


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    profile = user.get("profile") or db.get_or_create_user_profile(user)
    if (profile.get("subscription_tier") or "free").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return user


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

    if sort == "oldest":
        items.sort(key=lambda i: i.get("published_at") or "")
    elif sort == "engagement":
        items.sort(key=lambda i: i.get("engagement_raw") or 0, reverse=True)

    return {"items": items, "total": len(items)}


@app.post("/api/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    if _state["fetching"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_fetch_job)
    return {"status": "started"}


class SummaryRequest(BaseModel):
    url: str
    title: str
    category: str
    existing_summary: str = ""
    gemini_api_key: Optional[str] = None


@app.post("/api/summary")
def get_summary(req: SummaryRequest):
    using_own_key = bool(req.gemini_api_key)

    if not using_own_key:
        cached = get_cached_summary(req.url)
        if cached:
            return {"summary": cached, "cached": True}

    try:
        generated = summarize_article(
            url=req.url,
            title=req.title,
            category=req.category,
            existing_summary=req.existing_summary,
            api_key=req.gemini_api_key or os.environ.get("GEMINI_API_KEY"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {e}")

    if not using_own_key:
        save_summary_to_cache(req.url, generated)

    return {"summary": generated, "cached": False}


# ── Authenticated User Profile, Niche Section & Saved Items Endpoints ───────

class PreferencesUpdateRequest(BaseModel):
    preferred_depts: list[str] = Field(default_factory=list)
    preferred_sources: list[str] = Field(default_factory=list)


class NewsletterPrefsRequest(BaseModel):
    daily_newsletter: bool = False
    weekly_newsletter: bool = False


class SavedItemRequest(BaseModel):
    item_url: str
    title: str
    source: str = ""
    category: str = ""
    summary: str = ""
    custom_note: str = ""
    dept: list[str] = Field(default_factory=list)
    stack_tags: list[str] = Field(default_factory=list)


@app.get("/api/me")
def get_me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in required.")
    token = authorization.split(" ", 1)[1].strip()
    user_info = db.verify_user_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired login session.")
    try:
        profile = db.get_or_create_user_profile(user_info)
        if profile.get("subscription_tier") == "suspended":
            return {"profile": profile, "saved_items": [], "suspended": True}
        saved = db.list_saved_items(user_info["user_id"])
        return {"profile": profile, "saved_items": saved, "suspended": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load user profile: {e}")


@app.put("/api/me/preferences")
def put_preferences(
    req: PreferencesUpdateRequest,
    user: dict = Depends(get_current_user),
):
    try:
        updated = db.update_user_preferences(
            user_id=user["user_id"],
            preferred_depts=req.preferred_depts,
            preferred_sources=req.preferred_sources,
        )
        return {"profile": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not update preferences: {e}")


@app.put("/api/me/newsletter")
def put_newsletter_prefs(
    req: NewsletterPrefsRequest,
    user: dict = Depends(get_current_user),
):
    try:
        updated = db.update_user_newsletter_prefs(
            user_id=user["user_id"],
            daily_newsletter=req.daily_newsletter,
            weekly_newsletter=req.weekly_newsletter,
        )
        return {"profile": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not update newsletter settings: {e}")


@app.get("/api/me/saved")
def get_saved(user: dict = Depends(get_current_user)):
    try:
        saved = db.list_saved_items(user["user_id"])
        return {"saved_items": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load saved items: {e}")


@app.post("/api/me/saved")
def post_saved(req: SavedItemRequest, user: dict = Depends(get_current_user)):
    try:
        saved_row = db.save_or_update_user_item(user["user_id"], req.model_dump())
        return {"saved_item": saved_row}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save item: {e}")


@app.delete("/api/me/saved")
def remove_saved(
    item_url: str = Query(..., description="URL of the saved item to remove"),
    user: dict = Depends(get_current_user),
):
    try:
        db.delete_saved_item(user["user_id"], item_url)
        return {"deleted": True, "item_url": item_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete saved item: {e}")


# ── Admin Moderation & Role Management Endpoints ────────────────────────────

class AdminClaimRequest(BaseModel):
    admin_secret: str = ""
    target_tier: str = "admin"


@app.post("/api/admin/claim")
def post_claim_admin(
    req: AdminClaimRequest,
    user: dict = Depends(get_current_user),
):
    """Allows the site owner to elevate their account to ADMIN (using ADMIN_SECRET
    env var or default 'signal-admin-2026'), or switch their own account between
    FREE / PRO / ADMIN to test how each tier looks."""
    expected_secret = (os.environ.get("ADMIN_SECRET") or "signal-admin-2026").strip()
    current_tier = (user.get("profile", {}).get("subscription_tier") or "free").lower()

    # If user is already admin, or provides the valid admin secret, allow switching tier
    if current_tier != "admin" and req.admin_secret.strip() != expected_secret:
        raise HTTPException(
            status_code=403,
            detail="Invalid Admin Passcode. Set ADMIN_SECRET on Render (default: signal-admin-2026).",
        )
    try:
        updated = db.admin_set_user_tier(
            target_user_id=user["user_id"],
            target_email=user.get("email"),
            new_tier=req.target_tier or "admin",
        )
        return {"profile": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/admin/users")
def get_admin_users(_admin: dict = Depends(require_admin)):
    try:
        users = db.admin_list_users()
        return {"users": users, "total": len(users)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not list users: {e}")


class AdminUpdateTierRequest(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    tier: str = "free"


@app.put("/api/admin/users/tier")
def put_admin_user_tier(
    req: AdminUpdateTierRequest,
    _admin: dict = Depends(require_admin),
):
    try:
        updated = db.admin_set_user_tier(
            target_user_id=req.user_id,
            target_email=req.email,
            new_tier=req.tier,
        )
        return {"user": updated}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not update user tier: {e}")


@app.delete("/api/admin/items")
def delete_published_item(
    url: str = Query(..., description="URL of the published feed item to take down"),
    _admin: dict = Depends(require_admin),
):
    try:
        db.admin_delete_item(url)
        return {"deleted": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not remove item: {e}")


# ── Newsletter Preview, Test Send & Cron Dispatch Endpoints ─────────────────

@app.get("/api/newsletter/preview")
def preview_newsletter(
    kind: str = Query("daily", pattern="^(daily|weekly)$"),
    force_refresh: bool = False,
    gemini_api_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
):
    try:
        if kind == "weekly":
            issue = newsletter.build_or_get_weekly_issue(
                force_refresh=force_refresh,
                api_key=gemini_api_key,
            )
        else:
            issue = newsletter.build_or_get_daily_issue(
                force_refresh=force_refresh,
                api_key=gemini_api_key,
            )
        return {"issue": issue}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate newsletter preview: {e}")


class SendTestNewsletterRequest(BaseModel):
    kind: str = "daily"
    gemini_api_key: Optional[str] = None


@app.post("/api/newsletter/send-test")
def send_test_newsletter(
    req: SendTestNewsletterRequest,
    user: dict = Depends(get_current_user),
):
    try:
        issue = (
            newsletter.build_or_get_weekly_issue(api_key=req.gemini_api_key)
            if req.kind == "weekly"
            else newsletter.build_or_get_daily_issue(api_key=req.gemini_api_key)
        )
        delivery = newsletter.send_email_zero_cost(
            to_email=user["email"],
            subject=issue["subject"],
            html_body=issue["html_body"],
        )
        return {"delivery": delivery, "issue_key": issue["issue_key"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test email failed: {e}")


@app.post("/api/newsletter/dispatch")
def dispatch_newsletter(
    background_tasks: BackgroundTasks,
    kind: str = Query("daily", pattern="^(daily|weekly)$"),
):
    background_tasks.add_task(newsletter.dispatch_newsletter_batch, kind)
    return {"status": "dispatch_started", "kind": kind}


# ── Idea Network & AI Builder Chat Endpoints ────────────────────────────────

class IdeateNetworkRequest(BaseModel):
    url: str
    title: str
    category: str = "tech"
    summary: str = ""
    dept: list[str] = Field(default_factory=list)
    stack_tags: list[str] = Field(default_factory=list)
    education_level: str = "CS / Engineering Undergrad"
    builder_goal: str = "Weekend Hackathon / Resume Project"
    user_background: str = ""
    creativity_mode: str = "mashup"
    gemini_api_key: Optional[str] = None


@app.post("/api/ideate")
def post_ideate_network(req: IdeateNetworkRequest):
    try:
        all_items = db.load_items()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load items for network: {e}")

    connected_nodes = find_nearby_connected_items(
        anchor_url=req.url,
        anchor_title=req.title,
        anchor_depts=req.dept,
        anchor_stacks=req.stack_tags,
        all_items=all_items,
        max_nodes=4,
    )

    blueprint_html = generate_idea_network_blueprint(
        anchor_item={
            "url": req.url,
            "title": req.title,
            "category": req.category,
            "summary": req.summary,
            "dept": req.dept,
            "stack_tags": req.stack_tags,
        },
        connected_nodes=connected_nodes,
        education_level=req.education_level,
        builder_goal=req.builder_goal,
        user_background=req.user_background,
        creativity_mode=req.creativity_mode,
        api_key=req.gemini_api_key or os.environ.get("GEMINI_API_KEY"),
    )

    return {
        "connected_nodes": connected_nodes,
        "blueprint_html": blueprint_html,
    }


class ChatMessageItem(BaseModel):
    role: str
    content: str


class BuilderChatRequest(BaseModel):
    messages: list[ChatMessageItem] = Field(default_factory=list)
    context_item: Optional[dict] = None
    user_profile: Optional[dict] = None
    gemini_api_key: Optional[str] = None


@app.post("/api/chat")
def post_builder_chat(req: BuilderChatRequest):
    reply_html = chat_with_builder_ai(
        messages=[{"role": m.role, "content": m.content} for m in req.messages],
        context_item=req.context_item,
        user_profile=req.user_profile,
        api_key=req.gemini_api_key or os.environ.get("GEMINI_API_KEY"),
    )
    return {"reply_html": reply_html}


@app.get("/api/health")
def health():
    return {"ok": True}
