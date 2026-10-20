"""
Security-hardened FastAPI backend for Signal.
Supports 3 account tiers: FREE, PRO, and ADMIN (plus SUSPENDED access revocation).

Cybersecurity Protections Active:
1. Cryptographic Supabase JWT verification (no unsigned JWT decode fallback).
2. Sliding-window per-IP rate limiting on AI, Auth, Admin, and Refresh endpoints.
3. Constant-time `hmac.compare_digest` secret verification for Admin & Cron webhooks.
4. Server-side PRO/ADMIN tier enforcement on PRO endpoints (`/api/ideate`, `/api/chat`).
5. SSRF & OOM protection on URL scraping + strict HTML allowlist sanitization against XSS.
6. HTTP Security Headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `CSP`).
"""
import hmac
import os
import time
from collections import defaultdict, deque
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Header, Depends, Request
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

# Disable public /docs and /redoc in production unless ENABLE_DOCS=true
enable_docs = os.environ.get("ENABLE_DOCS", "").lower() == "true"
app = FastAPI(
    title="Signal API",
    docs_url="/docs" if enable_docs else None,
    redoc_url="/redoc" if enable_docs else None,
)

FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://signal-app-asd.pages.dev",
]
if os.environ.get("FRONTEND_ORIGIN"):
    FRONTEND_ORIGINS.append(os.environ["FRONTEND_ORIGIN"].rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Gemini-Key", "X-Cron-Secret"],
)


# ── HTTP Security Headers Middleware ────────────────────────────────────────

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


# ── Sliding-Window In-Memory Rate Limiter ───────────────────────────────────

_rate_buckets: dict[str, deque] = defaultdict(deque)
MAX_RATE_BUCKETS = 4096


def get_client_ip(request: Request) -> str:
    """Extracts the non-spoofable client IP set by Render/Cloudflare proxy:
    prefers CF-Connecting-IP or X-Real-IP, or falls back to the LAST hop
    appended to X-Forwarded-For by the reverse proxy."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()[:64]
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()[:64]
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1][:64]
    return (request.client.host if request.client else "unknown")[:64]


def enforce_rate_limit(bucket_name: str, client_id: str, max_calls: int, window_seconds: int):
    now = time.time()
    # Periodically evict stale keys so _rate_buckets never grows without bound
    if len(_rate_buckets) > MAX_RATE_BUCKETS:
        stale_keys = [
            k for k, dq in list(_rate_buckets.items())
            if not dq or (now - dq[-1]) > window_seconds
        ]
        for k in stale_keys:
            _rate_buckets.pop(k, None)

    key = f"{bucket_name}:{client_id}"
    q = _rate_buckets[key]
    while q and (now - q[0]) > window_seconds:
        q.popleft()
    if len(q) >= max_calls:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({max_calls} requests per {window_seconds}s). Please wait a moment.",
        )
    q.append(now)


_state = {"fetching": False, "last_error": None, "last_fetch_started_at": 0.0}
REFRESH_COOLDOWN_SECONDS = 120.0


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


def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    user_info = db.verify_user_token(token)
    if not user_info:
        return None
    profile = db.get_or_create_user_profile(user_info)
    user_info["profile"] = profile
    return user_info


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
        raise HTTPException(status_code=500, detail="Could not reach database.")

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
    source: Optional[str] = Query(None, max_length=80),
    category: Optional[str] = Query(None, max_length=80),
    stack: Optional[str] = Query(None, max_length=80),
    search: Optional[str] = Query(None, max_length=160),
    sort: str = Query("newest", pattern="^(newest|oldest|engagement)$"),
):
    try:
        items = db.load_items()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not reach database.")

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
def trigger_refresh(request: Request, background_tasks: BackgroundTasks):
    client_ip = get_client_ip(request)
    enforce_rate_limit("refresh", client_ip, max_calls=3, window_seconds=300)

    now = time.time()
    if _state["fetching"]:
        return {"status": "already_running"}
    if (now - float(_state.get("last_fetch_started_at") or 0.0)) < REFRESH_COOLDOWN_SECONDS:
        return {"status": "cooldown_active"}

    background_tasks.add_task(_run_fetch_job)
    return {"status": "started"}


class SummaryRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    title: str = Field(..., max_length=400)
    category: str = Field("tech", max_length=80)
    existing_summary: str = Field("", max_length=4000)
    gemini_api_key: Optional[str] = Field(None, max_length=256)


@app.post("/api/summary")
def get_summary(req: SummaryRequest, request: Request):
    """Generates or returns a cached 50-word AI summary.
    Security hardening against cache poisoning & Gemini key abuse:
    - Looks up `req.url` in our `items` table (`db.get_item_by_url`).
    - When using the server's GEMINI_API_KEY (not BYOK), requires `req.url` to exist
      in `items` and strictly uses the server-stored title, category, and snippet
      instead of trusting client-supplied `existing_summary`.
    """
    client_ip = get_client_ip(request)
    enforce_rate_limit("summary", client_ip, max_calls=15, window_seconds=60)

    using_own_key = bool(req.gemini_api_key and req.gemini_api_key.strip())
    known_item = db.get_item_by_url(req.url)

    if not using_own_key:
        if not known_item:
            raise HTTPException(
                status_code=404,
                detail="Item not found in Signal feed. Provide your own Gemini API key to summarize external URLs.",
            )
        cached = get_cached_summary(req.url)
        if cached and cached != db.ADMIN_REMOVED_MARKER:
            return {"summary": cached, "cached": True}

    trusted_title = known_item.get("title", req.title) if known_item else req.title
    trusted_category = known_item.get("category", req.category) if known_item else req.category
    # Never let unverified client `existing_summary` poison the shared summary cache
    trusted_existing_summary = (
        (known_item.get("summary") or "")
        if known_item
        else (req.existing_summary if using_own_key else "")
    )

    try:
        generated = summarize_article(
            url=req.url,
            title=trusted_title,
            category=trusted_category,
            existing_summary=trusted_existing_summary,
            api_key=(req.gemini_api_key.strip() if using_own_key else None) or os.environ.get("GEMINI_API_KEY"),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Summary generation failed.")

    if not using_own_key and known_item:
        save_summary_to_cache(req.url, generated)

    return {"summary": generated, "cached": False}


# ── Authenticated User Profile, Niche Section & Saved Items Endpoints ───────

class PreferencesUpdateRequest(BaseModel):
    preferred_depts: list[str] = Field(default_factory=list, max_length=20)
    preferred_sources: list[str] = Field(default_factory=list, max_length=50)


class NewsletterPrefsRequest(BaseModel):
    daily_newsletter: bool = False
    weekly_newsletter: bool = False


class SavedItemRequest(BaseModel):
    item_url: str = Field(..., max_length=2048)
    title: str = Field(..., max_length=400)
    source: str = Field("", max_length=120)
    category: str = Field("", max_length=80)
    summary: str = Field("", max_length=5000)
    custom_note: str = Field("", max_length=4000)
    dept: list[str] = Field(default_factory=list, max_length=15)
    stack_tags: list[str] = Field(default_factory=list, max_length=25)


@app.get("/api/me")
def get_me(user: Optional[dict] = Depends(get_optional_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired login session.")
    try:
        profile = user.get("profile") or db.get_or_create_user_profile(user)
        if profile.get("subscription_tier") == "suspended":
            return {"profile": profile, "saved_items": [], "suspended": True}
        saved = db.list_saved_items(user["user_id"])
        return {"profile": profile, "saved_items": saved, "suspended": False}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load user profile.")


@app.put("/api/me/preferences")
def put_preferences(
    req: PreferencesUpdateRequest,
    user: dict = Depends(get_current_user),
):
    tier = (user.get("profile", {}).get("subscription_tier") or "free").lower()
    clean_depts = [str(d)[:40] for d in req.preferred_depts[:20]]
    if tier == "free" and len(clean_depts) > 3:
        raise HTTPException(status_code=403, detail="Free accounts can select up to 3 niches. Upgrade to PRO for unlimited niches.")
    try:
        updated = db.update_user_preferences(
            user_id=user["user_id"],
            preferred_depts=clean_depts,
            preferred_sources=[str(s)[:80] for s in req.preferred_sources[:40]],
        )
        return {"profile": updated}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update preferences.")


@app.put("/api/me/newsletter")
def put_newsletter_prefs(
    req: NewsletterPrefsRequest,
    user: dict = Depends(get_current_user),
):
    tier = (user.get("profile", {}).get("subscription_tier") or "free").lower()
    weekly_allowed = req.weekly_newsletter if tier in ("pro", "admin") else False
    try:
        updated = db.update_user_newsletter_prefs(
            user_id=user["user_id"],
            daily_newsletter=req.daily_newsletter,
            weekly_newsletter=weekly_allowed,
        )
        return {"profile": updated}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update newsletter settings.")


@app.get("/api/me/saved")
def get_saved(user: dict = Depends(get_current_user)):
    try:
        saved = db.list_saved_items(user["user_id"])
        return {"saved_items": saved}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load saved items.")


@app.post("/api/me/saved")
def post_saved(req: SavedItemRequest, user: dict = Depends(get_current_user)):
    try:
        saved_row = db.save_or_update_user_item(user["user_id"], req.model_dump())
        return {"saved_item": saved_row}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save item.")


@app.delete("/api/me/saved")
def remove_saved(
    item_url: str = Query(..., max_length=2048, description="URL of the saved item to remove"),
    user: dict = Depends(get_current_user),
):
    try:
        db.delete_saved_item(user["user_id"], item_url)
        return {"deleted": True, "item_url": item_url}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not delete saved item.")


# ── Admin Moderation & Role Management Endpoints (Hardened) ─────────────────

class AdminClaimRequest(BaseModel):
    admin_secret: str = Field("", max_length=256)
    target_tier: str = Field("admin", pattern="^(free|pro|admin)$")


@app.post("/api/admin/claim")
def post_claim_admin(
    req: AdminClaimRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Hardened Admin elevation endpoint:
    - Rate-limited to 5 attempts per 15 minutes per IP to block brute-force attacks.
    - Requires ADMIN_SECRET environment variable to be explicitly set on Render
      (never falls back to a public default password).
    - Uses constant-time `hmac.compare_digest` to prevent timing attacks.
    """
    client_ip = get_client_ip(request)
    enforce_rate_limit("admin_claim", client_ip, max_calls=5, window_seconds=900)

    current_tier = (user.get("profile", {}).get("subscription_tier") or "free").lower()
    expected_secret = (os.environ.get("ADMIN_SECRET") or "").strip()

    if current_tier != "admin":
        if not expected_secret or len(expected_secret) < 10:
            raise HTTPException(
                status_code=403,
                detail="Admin passcode login is disabled until ADMIN_SECRET (min 10 chars) or ADMIN_EMAILS is set in Render Environment Variables.",
            )
        provided = req.admin_secret.strip()
        if not provided or not hmac.compare_digest(provided.encode("utf-8"), expected_secret.encode("utf-8")):
            raise HTTPException(status_code=403, detail="Invalid Admin Passcode.")
        # Non-admins authenticating with ADMIN_SECRET are strictly promoted to 'admin'
        target_tier = "admin"
    else:
        target_tier = req.target_tier or "admin"

    try:
        updated = db.admin_set_user_tier(
            target_user_id=user["user_id"],
            target_email=user.get("email"),
            new_tier=target_tier,
        )
        return {"profile": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/admin/users")
def get_admin_users(_admin: dict = Depends(require_admin)):
    try:
        users = db.admin_list_users()
        return {"users": users, "total": len(users)}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not list users.")


class AdminUpdateTierRequest(BaseModel):
    user_id: Optional[str] = Field(None, max_length=256)
    email: Optional[str] = Field(None, max_length=254)
    tier: str = Field("free", pattern="^(free|pro|admin|suspended)$")


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
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update user tier.")


@app.delete("/api/admin/items")
def delete_published_item(
    url: str = Query(..., max_length=2048, description="URL of the published feed item to take down"),
    _admin: dict = Depends(require_admin),
):
    try:
        db.admin_delete_item(url)
        return {"deleted": True, "url": url}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not remove item.")


# ── Newsletter Preview, Test Send & Cron Dispatch Endpoints ─────────────────

@app.get("/api/newsletter/preview")
def preview_newsletter(
    request: Request,
    kind: str = Query("daily", pattern="^(daily|weekly)$"),
    force_refresh: bool = False,
    gemini_api_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
    user: Optional[dict] = Depends(get_optional_user),
):
    client_ip = get_client_ip(request)
    enforce_rate_limit("newsletter_preview", client_ip, max_calls=15, window_seconds=60)

    # Only Admin can force-regenerate the shared newsletter cache
    is_admin_user = (user or {}).get("profile", {}).get("subscription_tier") == "admin"
    safe_force = force_refresh and is_admin_user

    try:
        if kind == "weekly":
            issue = newsletter.build_or_get_weekly_issue(
                force_refresh=safe_force,
                api_key=gemini_api_key,
            )
        else:
            issue = newsletter.build_or_get_daily_issue(
                force_refresh=safe_force,
                api_key=gemini_api_key,
            )
        return {"issue": issue}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not generate newsletter preview.")


class SendTestNewsletterRequest(BaseModel):
    kind: str = Field("daily", pattern="^(daily|weekly)$")
    gemini_api_key: Optional[str] = Field(None, max_length=256)


@app.post("/api/newsletter/send-test")
def send_test_newsletter(
    req: SendTestNewsletterRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    client_ip = get_client_ip(request)
    enforce_rate_limit("send_test_email", client_ip, max_calls=3, window_seconds=300)

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
    cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    user: Optional[dict] = Depends(get_optional_user),
):
    """Protected batch newsletter dispatch: requires either an Admin user token
    or a valid `X-Cron-Secret` header matching `CRON_SECRET` env var."""
    expected_cron = (os.environ.get("CRON_SECRET") or "").strip()
    is_admin_user = (user or {}).get("profile", {}).get("subscription_tier") == "admin"
    valid_cron = bool(
        expected_cron
        and cron_secret
        and hmac.compare_digest(cron_secret.strip().encode("utf-8"), expected_cron.encode("utf-8"))
    )

    if not is_admin_user and not valid_cron:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized newsletter dispatch. Requires Admin login or valid X-Cron-Secret header.",
        )

    background_tasks.add_task(newsletter.dispatch_newsletter_batch, kind)
    return {"status": "dispatch_started", "kind": kind}


# ── Idea Network & AI Builder Chat Endpoints (PRO / BYOK Enforced) ──────────

class IdeateNetworkRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    title: str = Field(..., max_length=400)
    category: str = Field("tech", max_length=80)
    summary: str = Field("", max_length=4000)
    dept: list[str] = Field(default_factory=list, max_length=15)
    stack_tags: list[str] = Field(default_factory=list, max_length=25)
    education_level: str = Field("CS / Engineering Undergrad", max_length=120)
    builder_goal: str = Field("Weekend Hackathon / Resume Project", max_length=120)
    user_background: str = Field("", max_length=300)
    creativity_mode: str = Field("mashup", max_length=40)
    gemini_api_key: Optional[str] = Field(None, max_length=256)


@app.post("/api/ideate")
def post_ideate_network(
    req: IdeateNetworkRequest,
    request: Request,
    user: Optional[dict] = Depends(get_optional_user),
):
    client_ip = get_client_ip(request)
    enforce_rate_limit("ideate", client_ip, max_calls=12, window_seconds=60)

    tier = ((user or {}).get("profile", {}).get("subscription_tier") or "free").lower()
    has_own_key = bool(req.gemini_api_key and req.gemini_api_key.strip())
    if tier not in ("pro", "admin") and not has_own_key:
        raise HTTPException(
            status_code=403,
            detail="Idea Network Blueprints require a Signal PRO account (or add your own free Gemini API key in 🔑 AI Key).",
        )

    try:
        all_items = db.load_items()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load items for network.")

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
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=4000)


class BuilderChatRequest(BaseModel):
    messages: list[ChatMessageItem] = Field(default_factory=list, max_length=25)
    context_item: Optional[dict] = None
    user_profile: Optional[dict] = None
    gemini_api_key: Optional[str] = Field(None, max_length=256)


@app.post("/api/chat")
def post_builder_chat(
    req: BuilderChatRequest,
    request: Request,
    user: Optional[dict] = Depends(get_optional_user),
):
    client_ip = get_client_ip(request)
    enforce_rate_limit("chat", client_ip, max_calls=12, window_seconds=60)

    tier = ((user or {}).get("profile", {}).get("subscription_tier") or "free").lower()
    has_own_key = bool(req.gemini_api_key and req.gemini_api_key.strip())
    if tier not in ("pro", "admin") and not has_own_key:
        raise HTTPException(
            status_code=403,
            detail="Multi-Turn AI Builder Chat requires a Signal PRO account (or add your own free Gemini API key in 🔑 AI Key).",
        )

    reply_html = chat_with_builder_ai(
        messages=[{"role": m.role, "content": m.content[:2000]} for m in req.messages[-12:]],
        context_item=req.context_item,
        user_profile=req.user_profile,
        api_key=req.gemini_api_key or os.environ.get("GEMINI_API_KEY"),
    )
    return {"reply_html": reply_html}


@app.get("/api/health")
def health():
    return {"ok": True}
