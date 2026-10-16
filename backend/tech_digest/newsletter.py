"""
Zero-cost Daily Top 10 & Weekly "How to Use It" AI Playbook Newsletter Engine.

Design principles to keep server & AI costs at ₹0:
1. External Traction Ranking (0 AI calls): Ranks stories by normalized engagement
   from the external website where they were posted (HN points, Reddit upvotes,
   GitHub stars, Product Hunt votes, Dev.to reactions, HF likes) using source
   percentile + source weight from config.py + cross-post bonus.
2. Generate Once, Cache in Supabase (1 Gemini call/day + 1 Gemini call/week):
   A single batched prompt generates the entire Daily Top 10 digest or Weekly
   Action Playbook and caches it in `newsletter_issues` by date/week key.
   Whether 1 user or 5,000 users preview or receive the newsletter, Gemini is
   only called once per issue.
3. Free Email Delivery: Supports built-in Gmail SMTP (`SMTP_EMAIL` +
   `SMTP_APP_PASSWORD`, ~500 free emails/day), Brevo (`BREVO_API_KEY`, 300/day
   free), or Resend (`RESEND_API_KEY`, 3,000/month free).
"""
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
# google.generativeai is imported lazily when api_key is set

from . import config, db

# Source weight lookup combining Tier 1 RSS weights and Tier 2/3 API weights
def _get_source_weight(source: str) -> float:
    if source in config.RSS_FEEDS:
        return config.RSS_FEEDS[source][1]
    if source == "Hacker News":
        return config.HN_WEIGHT
    if source == "arXiv":
        return config.ARXIV_WEIGHT
    if source.startswith("r/"):
        return config.REDDIT_WEIGHT
    if source.startswith("Hugging Face"):
        return config.HF_WEIGHT
    if source == "Lobsters":
        return config.LOBSTERS_WEIGHT
    if source == "IndieHackers":
        return config.INDIEHACKERS_WEIGHT
    if source == "Dev.to":
        return config.DEVTO_WEIGHT
    if source == "GitHub Trending":
        return config.GITHUB_WEIGHT
    if source == "Product Hunt":
        return config.PRODUCTHUNT_WEIGHT
    return 0.7


def rank_external_top_items(
    items: list[dict],
    lookback_hours: int = 48,
    top_n: int = 10,
    preferred_depts: Optional[list[str]] = None,
) -> list[dict]:
    """Ranks items by external traction on the source website where they were posted.
    Uses within-source percentile normalization so 300 HN points, 1,500 GitHub stars,
    and 80 Lobsters upvotes are compared fairly across platforms."""
    if not items:
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    recent = []
    for item in items:
        if preferred_depts:
            item_depts = item.get("dept") or []
            if not any(d in preferred_depts for d in item_depts):
                continue
        pub_str = item.get("published_at")
        if pub_str:
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt >= cutoff:
                    recent.append(item)
            except Exception:
                recent.append(item)
        else:
            recent.append(item)

    # Fall back to all matching items if lookback window has fewer than top_n items
    pool = recent if len(recent) >= top_n else [
        i for i in items
        if not preferred_depts or any(d in (i.get("dept") or []) for d in preferred_depts)
    ]
    if not pool:
        pool = items

    # Group by source to compute max engagement per source for normalization
    max_by_source: dict[str, float] = {}
    for item in pool:
        src = item.get("source", "unknown")
        eng = float(item.get("engagement_raw") or 0.0)
        if eng > max_by_source.get(src, 0.0):
            max_by_source[src] = eng

    scored = []
    for item in pool:
        src = item.get("source", "unknown")
        eng = float(item.get("engagement_raw") or 0.0)
        max_eng = max_by_source.get(src, 0.0)

        # Normalized 0..1 engagement score within its source platform
        if max_eng > 0:
            norm_eng = eng / max_eng
        else:
            # Tier 1 editorial RSS feeds without public upvote counts get a baseline
            norm_eng = 0.45

        weight = _get_source_weight(src)
        # Bonus if enrich.py detected cross-posting across multiple external sites
        summary_text = item.get("summary") or ""
        crosspost_bonus = 0.25 if "[also on " in summary_text else 0.0

        external_score = round((norm_eng * weight * 100.0) + (crosspost_bonus * 100.0), 1)
        enriched_copy = dict(item)
        enriched_copy["external_score"] = external_score
        scored.append(enriched_copy)

    scored.sort(key=lambda x: (x["external_score"], x.get("engagement_raw") or 0), reverse=True)

    # Ensure source diversity (max 3 items from the exact same source in Top 10)
    selected = []
    source_counts: dict[str, int] = {}
    for item in scored:
        src = item.get("source", "")
        if source_counts.get(src, 0) >= 3 and len(scored) > top_n:
            continue
        selected.append(item)
        source_counts[src] = source_counts.get(src, 0) + 1
        if len(selected) >= top_n:
            break

    return selected


def _generate_daily_top10_ai_blurb(top_items: list[dict], api_key: Optional[str]) -> list[str]:
    """Makes 1 single batched Gemini call to produce crisp ~45-word Inshorts summaries
    for all 10 items at once. Costs only 1 API request for the entire day."""
    if not api_key or not top_items:
        return [
            (item.get("summary") or f"Trending on {item.get('source')} in {item.get('category')}.")[:260]
            for item in top_items
        ]

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        numbered_input = "\n".join(
            f"{idx + 1}. Title: {it['title']} | Source: {it['source']} | "
            f"External Engagement: {int(it.get('engagement_raw') or 0)} | "
            f"Snippet: {(it.get('summary') or '')[:300]}"
            for idx, it in enumerate(top_items)
        )
        prompt = (
            "You are the editor of Signal, a fast-paced Inshorts-style tech digest.\n"
            "Below are today's Top 10 tech stories ranked by traction on their original platforms.\n"
            "Write a crisp, factual 40-to-50-word single-paragraph summary for each item (1 to 10).\n"
            "Return ONLY a valid JSON array of 10 strings (no markdown code fences, no HTML tags inside the strings).\n\n"
            f"{numbered_input}"
        )
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "", 1)
        elif text.startswith("```"):
            text = text.replace("```", "", 1)
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text.strip())
        if isinstance(parsed, list) and len(parsed) == len(top_items):
            return [str(x) for x in parsed]
    except Exception as e:
        print(f"[newsletter] Batched daily AI summary fallback: {e}")

    return [
        (item.get("summary") or f"High-traction {item.get('category')} story from {item.get('source')}.")[:260]
        for item in top_items
    ]


def build_or_get_daily_issue(force_refresh: bool = False, api_key: Optional[str] = None) -> dict:
    """Returns today's Daily Top 10 issue from cache, or generates & caches it once."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_key = f"daily-{today_str}"

    if not force_refresh:
        cached = db.get_newsletter_issue(issue_key)
        if cached:
            return cached

    all_items = db.load_items()
    top_10 = rank_external_top_items(all_items, lookback_hours=48, top_n=10)
    key_to_use = api_key or os.environ.get("GEMINI_API_KEY")
    blurbs = _generate_daily_top10_ai_blurb(top_10, key_to_use)

    for idx, item in enumerate(top_10):
        item["newsletter_blurb"] = blurbs[idx] if idx < len(blurbs) else (item.get("summary") or "")

    subject = f"⚡ Signal Daily Top 10 ({today_str}): Highest-Traction Tech Drops"
    rows_html = []
    for idx, item in enumerate(top_10):
        eng_badge = (
            f" · <b>▲ {int(item.get('engagement_raw') or 0)}</b> on {item['source']}"
            if (item.get("engagement_raw") or 0) > 0
            else f" · {item['source']}"
        )
        rows_html.append(
            f"""
            <div style="margin-bottom:18px;padding:14px 16px;background:#131316;border:1px solid #23242a;border-left:3px solid #ff8c1a;border-radius:6px;">
              <div style="font-size:11px;color:#8b8a85;font-family:monospace;text-transform:uppercase;margin-bottom:4px;">
                #{idx + 1} {eng_badge} · {item.get('category', 'tech')}
              </div>
              <a href="{item['url']}" style="font-size:16px;font-weight:700;color:#e8e6df;text-decoration:none;display:block;margin-bottom:6px;">
                {item['title']}
              </a>
              <p style="font-size:14px;color:#b8b6af;line-height:1.55;margin:0;">
                {item.get('newsletter_blurb', '')}
              </p>
            </div>
            """
        )

    html_body = f"""
    <div style="background:#0a0a0c;color:#e8e6df;font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;max-width:640px;margin:0 auto;border-radius:8px;">
      <div style="border-bottom:1px solid #23242a;padding-bottom:14px;margin-bottom:20px;">
        <span style="color:#ff8c1a;font-weight:800;font-size:20px;">▣ Signal</span>
        <span style="color:#8b8a85;font-family:monospace;font-size:12px;margin-left:8px;">DAILY TOP 10 · {today_str}</span>
        <p style="color:#8b8a85;font-size:13px;margin:6px 0 0;">
          The 10 highest-traction tech stories across Hacker News, GitHub, Reddit, Product Hunt, arXiv &amp; top engineering blogs — summarized in 50 words each.
        </p>
      </div>
      {''.join(rows_html)}
    </div>
    """.strip()

    issue = {
        "issue_key": issue_key,
        "kind": "daily",
        "subject": subject,
        "html_body": html_body,
        "items": top_10,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.save_newsletter_issue(issue)
    return issue


def build_or_get_weekly_issue(force_refresh: bool = False, api_key: Optional[str] = None) -> dict:
    """Generates & caches the Weekly 'How to Use This Week's Top Tech for Yourself' AI Playbook
    using 1 single Gemini call per week."""
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    issue_key = f"weekly-{iso_year}-W{iso_week:02d}"

    if not force_refresh:
        cached = db.get_newsletter_issue(issue_key)
        if cached:
            return cached

    all_items = db.load_items()
    top_weekly = rank_external_top_items(all_items, lookback_hours=24 * 7, top_n=12)
    key_to_use = api_key or os.environ.get("GEMINI_API_KEY")

    playbook_html = ""
    if key_to_use and top_weekly:
        try:
            import google.generativeai as genai
            genai.configure(api_key=key_to_use)
            model = genai.GenerativeModel("gemini-2.5-flash")
            digest_lines = "\n".join(
                f"- [{it['title']}]({it['url']}) ({it['source']}, ▲{int(it.get('engagement_raw') or 0)}, "
                f"depts: {', '.join(it.get('dept') or ['general'])}, stack: {', '.join(it.get('stack_tags') or [])}): "
                f"{(it.get('summary') or '')[:250]}"
                for it in top_weekly
            )
            prompt = (
                "You are a pragmatic staff engineer and startup advisor writing Signal's Weekly 'How to Use It For Yourself' Playbook.\n"
                "Based on this week's top-traction tech stories and launches below, write an actionable guide telling the reader "
                "how they can personally use, apply, or build on this week's breakthroughs.\n\n"
                f"This Week's Top Stories:\n{digest_lines}\n\n"
                "Structure your output in clean HTML (using only <h3>, <p>, <ul>, <li>, <b>, <a> tags) with these 4 concise sections:\n"
                "1. <h3>🛠️ Tools & Repos You Can Plug Into Your Workflow Today</h3> (3 concrete picks from the list and how to use them)\n"
                "2. <h3>🧠 Architecture & Engineering Lessons to Steal</h3> (2 practical takeaways for your own code/projects)\n"
                "3. <h3>🚀 Weekend Builder Opportunity</h3> (1 specific micro-SaaS or open-source project idea inspired by this week's launches, including suggested stack)\n"
                "4. <h3>⚡ 60-Second Action Checklist for Next Week</h3> (3 bullet points the reader can execute in under an hour)\n"
                "Keep the entire guide crisp, specific, and grounded in the links above (around 300-400 words total)."
            )
            resp = model.generate_content(prompt)
            playbook_html = resp.text.strip()
            if playbook_html.startswith("```html"):
                playbook_html = playbook_html.replace("```html", "", 1)
            elif playbook_html.startswith("```"):
                playbook_html = playbook_html.replace("```", "", 1)
            if playbook_html.endswith("```"):
                playbook_html = playbook_html.rsplit("```", 1)[0]
            playbook_html = playbook_html.strip()
        except Exception as e:
            print(f"[newsletter] Weekly playbook AI fallback: {e}")

    if not playbook_html:
        top_links = "".join(
            f"<li><a href='{it['url']}' style='color:#ff8c1a;'>{it['title']}</a> ({it['source']}) — {(it.get('summary') or 'High-signal release.')[:140]}</li>"
            for it in top_weekly[:5]
        )
        playbook_html = f"""
        <h3>🛠️ Tools &amp; Launches to Try This Week</h3>
        <p>Here are this week's highest-traction releases and how you can apply them to your own workflow:</p>
        <ul>{top_links}</ul>
        <h3>🚀 How to Apply This Week's Signal</h3>
        <ul>
          <li><b>Benchmark against your current stack:</b> Pick the top launch above in your primary department and test whether it replaces boilerplate in your current side project.</li>
          <li><b>Ship a focused wrapper or integration:</b> High-engagement infrastructure drops on GitHub and Hacker News often lack beginner-friendly UIs or templates—building one is the fastest weekend project wedge.</li>
          <li><b>Set GEMINI_API_KEY:</b> Add your free Gemini API key in Signal to unlock full AI-synthesized weekly playbooks tailored to each week's corpus.</li>
        </ul>
        """.strip()

    subject = f"🧠 Signal Weekly Playbook ({iso_year}-W{iso_week:02d}): How to Use This Week's Top Tech"
    html_body = f"""
    <div style="background:#0a0a0c;color:#e8e6df;font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;padding:24px;max-width:640px;margin:0 auto;border-radius:8px;">
      <div style="border-bottom:1px solid #23242a;padding-bottom:14px;margin-bottom:20px;">
        <span style="color:#ff8c1a;font-weight:800;font-size:20px;">▣ Signal</span>
        <span style="color:#7aa2ff;font-family:monospace;font-size:12px;margin-left:8px;">WEEKLY AI PLAYBOOK · {iso_year}-W{iso_week:02d}</span>
        <p style="color:#8b8a85;font-size:13px;margin:6px 0 0;">
          How to practically use this week's top-engaged tech stories, repos, and research for your own projects and career.
        </p>
      </div>
      <div style="font-size:14px;line-height:1.65;color:#e8e6df;">
        {playbook_html}
      </div>
    </div>
    """.strip()

    issue = {
        "issue_key": issue_key,
        "kind": "weekly",
        "subject": subject,
        "html_body": html_body,
        "items": top_weekly,
        "created_at": now.isoformat(),
    }
    db.save_newsletter_issue(issue)
    return issue


def send_email_zero_cost(to_email: str, subject: str, html_body: str) -> dict:
    """Sends an HTML email using whichever free-tier provider is configured in env vars:
    1. Gmail SMTP (`SMTP_EMAIL` + `SMTP_APP_PASSWORD`) — built-in, 100% free (~500/day)
    2. Brevo API (`BREVO_API_KEY` + optional `SENDER_EMAIL`) — 300/day free
    3. Resend API (`RESEND_API_KEY` + optional `SENDER_EMAIL`) — 100/day (3,000/mo) free
    """
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_APP_PASSWORD")
    brevo_key = os.environ.get("BREVO_API_KEY")
    resend_key = os.environ.get("RESEND_API_KEY")
    sender_email = os.environ.get("SENDER_EMAIL") or smtp_email or "onboarding@resend.dev"

    if smtp_email and smtp_password:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Signal Digest <{smtp_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, [to_email], msg.as_string())
        return {"sent": True, "provider": "gmail_smtp", "to": to_email}

    if brevo_key:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": brevo_key, "Content-Type": "application/json"},
            json={
                "sender": {"name": "Signal Digest", "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_body,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {"sent": True, "provider": "brevo", "to": to_email}

    if resend_key:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
            json={
                "from": f"Signal Digest <{sender_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {"sent": True, "provider": "resend", "to": to_email}

    return {
        "sent": False,
        "provider": "none_configured",
        "to": to_email,
        "message": (
            "Email preview generated! To deliver emails to inboxes for ₹0, add SMTP_EMAIL + "
            "SMTP_APP_PASSWORD (Gmail App Password) or BREVO_API_KEY in Render Environment Variables."
        ),
    }


def dispatch_newsletter_batch(kind: str = "daily") -> dict:
    """Generates the daily or weekly issue once, then sends it to all subscribed users."""
    issue = (
        build_or_get_weekly_issue()
        if kind == "weekly"
        else build_or_get_daily_issue()
    )
    subscribers = db.list_newsletter_subscribers(kind=kind)
    sent_count = 0
    skipped_provider = False
    errors = []

    for sub in subscribers:
        email = sub.get("email")
        if not email:
            continue
        try:
            res = send_email_zero_cost(email, issue["subject"], issue["html_body"])
            if res.get("sent"):
                sent_count += 1
            else:
                skipped_provider = True
                break
        except Exception as e:
            errors.append(f"{email}: {e}")

    return {
        "kind": kind,
        "issue_key": issue["issue_key"],
        "subscribers_matched": len(subscribers),
        "emails_sent": sent_count,
        "email_provider_configured": not skipped_provider,
        "errors": errors,
    }
