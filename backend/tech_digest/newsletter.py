"""
Zero-cost Daily Top 10 & Weekly "How to Use It" AI Playbook Newsletter Engine.

Key fixes for inbox readability & reliability:
1. High-contrast email-safe HTML + plain-text fallback: Uses dark text (#111827) on
   clean light cards (#ffffff / #f9fafb) for emails so Gmail never renders invisible
   white-on-white text when stripping dark backgrounds.
2. Never caches an empty issue: If `items` is empty or a cached issue has 0 items,
   regenerates automatically from the live database.
3. Supports HTTPS port 443 delivery (Google Apps Script Webhook, Brevo, Resend) as
   well as Gmail SMTP.
"""
import html
import json
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from . import config, db


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


def _clean_html_entities(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def rank_external_top_items(
    items: list[dict],
    lookback_hours: int = 48,
    top_n: int = 10,
    preferred_depts: Optional[list[str]] = None,
) -> list[dict]:
    """Ranks items by external traction on the source website where they were posted."""
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

    pool = recent if len(recent) >= top_n else [
        i for i in items
        if not preferred_depts or any(d in (i.get("dept") or []) for d in preferred_depts)
    ]
    if not pool:
        pool = items

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

        norm_eng = (eng / max_eng) if max_eng > 0 else 0.45
        weight = _get_source_weight(src)
        summary_text = item.get("summary") or ""
        crosspost_bonus = 0.25 if "[also on " in summary_text else 0.0

        external_score = round((norm_eng * weight * 100.0) + (crosspost_bonus * 100.0), 1)
        enriched_copy = dict(item)
        enriched_copy["external_score"] = external_score
        scored.append(enriched_copy)

    scored.sort(key=lambda x: (x["external_score"], x.get("engagement_raw") or 0), reverse=True)

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
    for all 10 items at once."""
    fallback_blurbs = [
        _clean_html_entities(item.get("summary") or "")[:260]
        or f"High-traction {item.get('category', 'tech')} story trending on {item.get('source', 'tech feed')}."
        for item in top_items
    ]
    if not api_key or not top_items:
        return fallback_blurbs

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        numbered_input = "\n".join(
            f"{idx + 1}. Title: {it['title']} | Source: {it['source']} | "
            f"External Engagement: {int(it.get('engagement_raw') or 0)} | "
            f"Snippet: {_clean_html_entities(it.get('summary') or '')[:300]}"
            for idx, it in enumerate(top_items)
        )
        prompt = (
            "You are the editor of Signal, a fast-paced Inshorts-style tech digest.\n"
            "Below are today's Top 10 tech stories ranked by traction on their original platforms.\n"
            "Write a crisp, factual 40-to-50-word single-paragraph summary for each item (1 to 10).\n"
            "Return ONLY a valid JSON array of 10 plain-text strings (no markdown code fences, no HTML tags).\n\n"
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
            return [_clean_html_entities(str(x)) for x in parsed]
    except Exception as e:
        print(f"[newsletter] Batched daily AI summary fallback: {e}")

    return fallback_blurbs


def build_or_get_daily_issue(force_refresh: bool = False, api_key: Optional[str] = None) -> dict:
    """Returns today's Daily Top 10 issue from cache, or generates & caches it once.
    Uses email-safe high-contrast styling (#111827 text on #ffffff cards) so Gmail never
    renders invisible white-on-white text."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_key = f"daily-{today_str}"

    if not force_refresh:
        cached = db.get_newsletter_issue(issue_key)
        # Only use cache if it actually has items and non-empty HTML
        if cached and cached.get("items") and len(cached.get("items")) > 0 and cached.get("html_body"):
            return cached

    all_items = db.load_items()
    top_10 = rank_external_top_items(all_items, lookback_hours=48, top_n=10)
    key_to_use = api_key or os.environ.get("GEMINI_API_KEY")
    blurbs = _generate_daily_top10_ai_blurb(top_10, key_to_use)

    for idx, item in enumerate(top_10):
        item["newsletter_blurb"] = blurbs[idx] if idx < len(blurbs) else _clean_html_entities(item.get("summary") or "")

    subject = f"⚡ Signal Daily Top 10 ({today_str}): Highest-Traction Tech Drops"
    rows_html = []
    for idx, item in enumerate(top_10):
        eng_raw = int(item.get("engagement_raw") or 0)
        eng_badge = (
            f" · <strong style='color:#15803d;'>▲ {eng_raw}</strong> on {html.escape(item['source'])}"
            if eng_raw > 0
            else f" · {html.escape(item['source'])}"
        )
        title_escaped = html.escape(_clean_html_entities(item["title"]))
        blurb_escaped = html.escape(item.get("newsletter_blurb") or "Read full story on the source site.")
        rows_html.append(
            f"""
            <div style="margin-bottom:14px;padding:14px 16px;background-color:#ffffff;color:#111827;border:1px solid #e5e7eb;border-left:4px solid #ff8c1a;border-radius:6px;">
              <div style="font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase;margin-bottom:4px;">
                #{idx + 1}{eng_badge} · {html.escape(item.get('category', 'tech'))}
              </div>
              <a href="{item['url']}" target="_blank" rel="noreferrer" style="font-size:16px;font-weight:700;color:#111827;text-decoration:underline;display:block;margin-bottom:6px;line-height:1.35;">
                {title_escaped}
              </a>
              <p style="font-size:14px;color:#374151;line-height:1.55;margin:0;">
                {blurb_escaped}
              </p>
            </div>
            """
        )

    if not rows_html:
        rows_html.append(
            "<p style='color:#111827;font-size:14px;'>No feed items loaded yet. Click 'Refresh now' in Signal to fetch the latest stories.</p>"
        )

    html_body = f"""
    <div style="background-color:#f3f4f6;color:#111827;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px;max-width:640px;margin:0 auto;border-radius:8px;">
      <div style="background-color:#111827;color:#ffffff;padding:16px 18px;border-radius:6px;margin-bottom:16px;">
        <span style="color:#ff8c1a;font-weight:800;font-size:20px;">▣ Signal</span>
        <span style="color:#9ca3af;font-family:monospace;font-size:12px;margin-left:8px;">DAILY TOP 10 · {today_str}</span>
        <p style="color:#d1d5db;font-size:13px;margin:6px 0 0;line-height:1.45;">
          The 10 highest-traction tech stories across Hacker News, GitHub, Reddit, Product Hunt, arXiv &amp; engineering blogs — in 50 words each.
        </p>
      </div>
      {''.join(rows_html)}
      <div style="text-align:center;font-size:12px;color:#6b7280;margin-top:16px;padding-top:12px;border-top:1px solid #e5e7eb;">
        Sent by <a href="https://signal-app-asd.pages.dev" style="color:#ea580c;font-weight:600;">Signal Tech Digest</a>
      </div>
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
    if top_10:
        db.save_newsletter_issue(issue)
    return issue


def build_or_get_weekly_issue(force_refresh: bool = False, api_key: Optional[str] = None) -> dict:
    """Generates & caches the Weekly 'How to Use This Week's Top Tech for Yourself' AI Playbook."""
    now = datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    issue_key = f"weekly-{iso_year}-W{iso_week:02d}"

    if not force_refresh:
        cached = db.get_newsletter_issue(issue_key)
        if cached and cached.get("items") and len(cached.get("items")) > 0 and cached.get("html_body"):
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
                f"- [{_clean_html_entities(it['title'])}]({it['url']}) ({it['source']}, ▲{int(it.get('engagement_raw') or 0)}, "
                f"depts: {', '.join(it.get('dept') or ['general'])}, stack: {', '.join(it.get('stack_tags') or [])}): "
                f"{_clean_html_entities(it.get('summary') or '')[:250]}"
                for it in top_weekly
            )
            prompt = (
                "You are a pragmatic staff engineer and startup advisor writing Signal's Weekly 'How to Use It For Yourself' Playbook.\n"
                "Based on this week's top-traction tech stories and launches below, write an actionable guide telling the reader "
                "how they can personally use, apply, or build on this week's breakthroughs.\n\n"
                f"This Week's Top Stories:\n{digest_lines}\n\n"
                "Structure your output in clean HTML (using only <h3>, <p>, <ul>, <li>, <b>, <a href='...'> tags) with these 4 concise sections:\n"
                "1. <h3>🛠️ Tools & Repos You Can Plug Into Your Workflow Today</h3> (3 concrete picks from the list and how to use them)\n"
                "2. <h3>🧠 Architecture & Engineering Lessons to Steal</h3> (2 practical takeaways for your own code/projects)\n"
                "3. <h3>🚀 Weekend Builder Opportunity</h3> (1 specific micro-SaaS or open-source project idea inspired by this week's launches, including suggested stack)\n"
                "4. <h3>⚡ 60-Second Action Checklist for Next Week</h3> (3 bullet points the reader can execute in under an hour)\n"
                "Keep the entire guide crisp, specific, and grounded in the links above (around 300-350 words total)."
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
            f"<li style='margin-bottom:8px;'><a href='{it['url']}' style='color:#ea580c;font-weight:600;'>{html.escape(_clean_html_entities(it['title']))}</a> ({html.escape(it['source'])}) — {html.escape(_clean_html_entities(it.get('summary') or 'High-signal release.')[:140])}</li>"
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
          <li><b>Enable Gemini AI Key:</b> Add your free Gemini API key in Signal (or Render env vars) to synthesize custom weekly playbooks automatically.</li>
        </ul>
        """.strip()

    subject = f"🧠 Signal Weekly Playbook ({iso_year}-W{iso_week:02d}): How to Use This Week's Top Tech"
    html_body = f"""
    <div style="background-color:#f3f4f6;color:#111827;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px;max-width:640px;margin:0 auto;border-radius:8px;">
      <div style="background-color:#111827;color:#ffffff;padding:16px 18px;border-radius:6px;margin-bottom:16px;">
        <span style="color:#ff8c1a;font-weight:800;font-size:20px;">▣ Signal</span>
        <span style="color:#93c5fd;font-family:monospace;font-size:12px;margin-left:8px;">WEEKLY AI PLAYBOOK · {iso_year}-W{iso_week:02d}</span>
        <p style="color:#d1d5db;font-size:13px;margin:6px 0 0;line-height:1.45;">
          How to practically use this week's top-engaged tech stories, repos, and research for your own projects.
        </p>
      </div>
      <div style="background-color:#ffffff;color:#111827;padding:18px 20px;border:1px solid #e5e7eb;border-radius:6px;font-size:14px;line-height:1.65;">
        {playbook_html}
      </div>
      <div style="text-align:center;font-size:12px;color:#6b7280;margin-top:16px;padding-top:12px;border-top:1px solid #e5e7eb;">
        Sent by <a href="https://signal-app-asd.pages.dev" style="color:#ea580c;font-weight:600;">Signal Tech Digest</a>
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
    if top_weekly:
        db.save_newsletter_issue(issue)
    return issue


def _html_to_plain_text(html_body: str) -> str:
    """Builds a clean plain-text version of the newsletter so every email client
    (and Google Apps Script's plain-text fallback parameter) always has readable text."""
    text = re.sub(r"</?(div|p|h3|li|ul|br)[^>]*>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n\n".join(lines)


def send_email_zero_cost(to_email: str, subject: str, html_body: str) -> dict:
    """Sends both HTML + plain-text email over HTTPS (port 443) or SMTP."""
    gmail_webhook = os.environ.get("GMAIL_WEBHOOK_URL")
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_APP_PASSWORD")
    brevo_key = os.environ.get("BREVO_API_KEY")
    resend_key = os.environ.get("RESEND_API_KEY")
    sender_email = os.environ.get("SENDER_EMAIL") or smtp_email or "onboarding@resend.dev"

    plain_body = _html_to_plain_text(html_body)

    if gmail_webhook:
        resp = requests.post(
            gmail_webhook.strip(),
            json={
                "to": to_email,
                "subject": subject,
                "text": plain_body,
                "html": html_body,
                "htmlBody": html_body,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return {"sent": True, "provider": "gmail_https_webhook", "to": to_email}

    if brevo_key:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": brevo_key, "Content-Type": "application/json"},
            json={
                "sender": {"name": "Signal Digest", "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "textContent": plain_body,
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
                "text": plain_body,
                "html": html_body,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {"sent": True, "provider": "resend", "to": to_email}

    if smtp_email and smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Signal Digest <{smtp_email}>"
            msg["To"] = to_email
            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                server.login(smtp_email, smtp_password)
                server.sendmail(smtp_email, [to_email], msg.as_string())
            return {"sent": True, "provider": "gmail_smtp", "to": to_email}
        except Exception as smtp_err:
            raise RuntimeError(
                f"SMTP connection blocked ({smtp_err}). Render Free Tier blocks port 465—add GMAIL_WEBHOOK_URL (Google Apps Script) in Render Environment Variables."
            )

    return {
        "sent": False,
        "provider": "none_configured",
        "to": to_email,
        "message": (
            "Email preview is ready! To send to your Gmail inbox from Render Free Tier, "
            "set GMAIL_WEBHOOK_URL (Google Apps Script) or BREVO_API_KEY in Render Environment Variables."
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
