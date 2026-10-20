import html
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
# google.generativeai imported lazily inside functions

_ideate_mem_cache: dict[str, str] = {}
MAX_SCRAPE_BYTES = 262_144  # 256 KB max download to prevent memory-exhaustion DoS

ALLOWED_AI_TAGS = {"p", "b", "strong", "i", "em", "u", "ul", "ol", "li", "br", "code", "pre", "h3", "h4", "a"}


def is_safe_public_url(url: str) -> bool:
    """SSRF Guard: Verifies that `url` uses http/https and resolves strictly to
    a public routable IP address (blocks 127.0.0.1, 10.x.x.x, 192.168.x.x,
    172.16-31.x.x, and cloud metadata 169.254.169.254)."""
    if not url or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname or hostname in ("localhost", "0.0.0.0", "::1") or hostname.endswith(".local") or hostname.endswith(".internal"):
            return False

        # Resolve DNS and inspect every returned IP
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        if not addr_info:
            return False
        for entry in addr_info:
            ip_str = entry[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def sanitize_ai_html(raw_html: str) -> str:
    """XSS Guard: Parses HTML with BeautifulSoup and strips any tag not in
    ALLOWED_AI_TAGS, removes all `on*` event attributes (`onerror`, `onclick`, etc.)
    and `style` attributes, and enforces `http/https` on `<a href>`."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(True):
        tag_name = tag.name.lower()
        if tag_name in ("script", "style", "iframe", "object", "embed", "svg", "form", "input", "button", "meta", "link"):
            tag.decompose()
            continue
        if tag_name not in ALLOWED_AI_TAGS:
            tag.unwrap()
            continue
        # Only allow safe href on <a> tags
        clean_attrs = {}
        if tag_name == "a":
            href = (tag.get("href") or "").strip()
            if href.startswith("https://") or href.startswith("http://"):
                clean_attrs["href"] = href
                clean_attrs["target"] = "_blank"
                clean_attrs["rel"] = "noopener noreferrer"
        tag.attrs = clean_attrs
    return str(soup).strip()


def fetch_article_content(url: str, existing_summary: str = "") -> str:
    """Fast-scrapes the body content of the webpage (3.5s timeout, 256 KB stream cap,
    SSRF-protected). If existing_summary already has substantial text (>= 220 chars),
    skips network scraping."""
    if existing_summary and len(existing_summary.strip()) >= 220:
        return existing_summary.strip()[:3500]

    if not is_safe_public_url(url):
        print(f"[security] Blocked unsafe or internal URL scrape: {url}")
        return existing_summary[:3500] if existing_summary else ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SignalTechDigest/1.0)"
        }
        res = requests.get(
            url,
            headers=headers,
            timeout=3.5,
            allow_redirects=False,  # Prevent open-redirect SSRF to internal IPs
            stream=True,
        )
        res.raise_for_status()

        chunks = []
        downloaded = 0
        for chunk in res.iter_content(chunk_size=16_384):
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if downloaded >= MAX_SCRAPE_BYTES:
                break
        res.close()
        raw_html = b"".join(chunks).decode("utf-8", errors="ignore")

        soup = BeautifulSoup(raw_html, "html.parser")
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
        text = " ".join([p for p in paragraphs if len(p) > 40])
        return text[:3500]
    except Exception as e:
        print(f"Fast scrape fallback for {url}: {e}")
        return existing_summary[:3500] if existing_summary else ""


def summarize_article(
    url: str,
    title: str,
    category: str,
    existing_summary: str,
    api_key: str | None = None,
) -> str:
    """Generates a ~50-word Inshorts-style summary using Gemini or fallback mock."""
    safe_title = html.escape((title or "")[:300])
    safe_cat = html.escape((category or "tech")[:60])

    if not api_key:
        mock_summary = f"""
        <p><b>[Mock Summary]</b> This 50-word Inshorts-style placeholder covers <i>{safe_cat}</i> for &ldquo;{safe_title}&rdquo;. It highlights the core architectural tradeoffs between throughput and state synchronization in modern distributed systems, showing how teams decouple stateful storage from stateless compute to scale reliably. <i>(Add a Gemini API key to enable live summaries.)</i></p>
        """
        return sanitize_ai_html(mock_summary.strip())

    try:
        content = fetch_article_content(url, existing_summary=existing_summary)
        if not content:
            content = f"Title: {title}. Context summary: {existing_summary}"

        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = (
            f"You are an editor for a fast-paced tech news digest like Inshorts. "
            f"Write a crisp, high-signal summary of the following article in strictly 45 to 55 words "
            f"(2 to 3 concise sentences).\n\n"
            f"Title: {title[:300]}\n"
            f"Category: {category[:60]}\n"
            f"Content:\n{content[:3500]}\n\n"
            f"Guidelines:\n"
            f"- Lead immediately with the core news, launch, or technical finding (avoid filler like 'This article discusses').\n"
            f"- Keep the total word count around 50 words (never exceed 60 words).\n"
            f"- Return a single clean HTML paragraph (<p>...</p>) using <b> sparingly for 1-2 key terms."
        )

        response = model.generate_content(prompt)
        summary = response.text.strip()

        if summary.startswith("```html"):
            summary = summary.replace("```html", "", 1)
        elif summary.startswith("```"):
            summary = summary.replace("```", "", 1)
        if summary.endswith("```"):
            summary = summary.rsplit("```", 1)[0]

        return sanitize_ai_html(summary.strip())

    except Exception as e:
        return f"<p>Failed to generate summary: {html.escape(str(e)[:200])}</p>"


# ── Idea Network & Personalized Creativity Engine ────────────────────────────

def find_nearby_connected_items(
    anchor_url: str,
    anchor_title: str,
    anchor_depts: list[str],
    anchor_stacks: list[str],
    all_items: list[dict],
    max_nodes: int = 4,
) -> list[dict]:
    """Finds 4 connected drops from nearby days in Signal's database in <2ms."""
    anchor_words = {
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9]+", anchor_title or "")
        if len(w) > 3
    }
    anchor_dept_set = set(anchor_depts or [])
    anchor_stack_set = {s.lower() for s in (anchor_stacks or [])}

    direct_candidates = []
    bridge_candidates = []

    for item in all_items[:400]:
        url = item.get("url") or ""
        if not url or url == anchor_url:
            continue

        item_depts = set(item.get("dept") or [])
        item_stacks = {s.lower() for s in (item.get("stack_tags") or [])}
        item_words = {
            w.lower()
            for w in re.findall(r"[a-zA-Z0-9]+", item.get("title") or "")
            if len(w) > 3
        }

        shared_stacks = anchor_stack_set & item_stacks
        shared_depts = anchor_dept_set & item_depts
        shared_words = anchor_words & item_words
        eng = float(item.get("engagement_raw") or 0.0)
        is_idea = bool(item.get("is_builder_idea")) or item.get("category") in ("launch", "idea")

        if shared_stacks or shared_depts or shared_words:
            synergy_score = (
                len(shared_stacks) * 35
                + len(shared_depts) * 20
                + len(shared_words) * 15
                + (20 if is_idea else 0)
                + min(eng / 20.0, 25.0)
            )
            reason_parts = []
            if shared_stacks:
                reason_parts.append(f"shares stack ({', '.join(sorted(shared_stacks))})")
            if shared_depts:
                reason_parts.append(f"same domain ({', '.join(sorted(shared_depts))})")
            if shared_words and not reason_parts:
                reason_parts.append(f"related topic ({', '.join(list(shared_words)[:2])})")
            direct_candidates.append({
                "title": item.get("title", ""),
                "url": url,
                "source": item.get("source", ""),
                "category": item.get("category", ""),
                "dept": list(item_depts),
                "stack_tags": item.get("stack_tags") or [],
                "summary": (item.get("summary") or "")[:180],
                "connection_type": "Direct Synergy",
                "connection_reason": " + ".join(reason_parts) or "Related recent drop",
                "_score": synergy_score,
            })
        else:
            bridge_score = (30 if is_idea else 0) + min(eng / 15.0, 40.0) + (len(item_stacks) * 10)
            bridge_dept = ", ".join(list(item_depts)[:2]) or item.get("category", "tech")
            bridge_candidates.append({
                "title": item.get("title", ""),
                "url": url,
                "source": item.get("source", ""),
                "category": item.get("category", ""),
                "dept": list(item_depts),
                "stack_tags": item.get("stack_tags") or [],
                "summary": (item.get("summary") or "")[:180],
                "connection_type": "Cross-Domain Bridge",
                "connection_reason": f"Adjacent drop in {bridge_dept}",
                "_score": bridge_score,
            })

    direct_candidates.sort(key=lambda x: x["_score"], reverse=True)
    bridge_candidates.sort(key=lambda x: x["_score"], reverse=True)

    selected = direct_candidates[:2] + bridge_candidates[:2]
    if len(selected) < max_nodes:
        remaining = [c for c in (direct_candidates[2:] + bridge_candidates[2:]) if c not in selected]
        selected.extend(remaining[: max_nodes - len(selected)])

    for node in selected:
        node.pop("_score", None)
    return selected[:max_nodes]


def generate_idea_network_blueprint(
    anchor_item: dict,
    connected_nodes: list[dict],
    education_level: str,
    builder_goal: str,
    user_background: str,
    creativity_mode: str,
    api_key: str | None = None,
) -> str:
    """Generates a fast, minimum-fluff 4-point blueprint (XSS-sanitized)."""
    title = (anchor_item.get("title") or "this tech drop")[:300]
    category = (anchor_item.get("category") or "tech")[:60]
    stacks = ", ".join((anchor_item.get("stack_tags") or [])[:10]) or "Python / TypeScript / REST APIs"

    cache_key = f"{anchor_item.get('url')}|{education_level}|{builder_goal}|{user_background.strip().lower()[:120]}|{creativity_mode}|{bool(api_key)}"
    if cache_key in _ideate_mem_cache:
        return _ideate_mem_cache[cache_key]

    if not api_key:
        connected_titles = ", ".join(n["title"] for n in connected_nodes[:2]) or "recent Signal drops"
        mock_html = f"""
        <ul>
          <li><b>🛠️ Tech Stack:</b> {html.escape(stacks)} (calibrated for {html.escape(builder_goal)}).</li>
          <li><b>📚 Prerequisites:</b> {html.escape(education_level)} fundamentals{f' + your {html.escape(user_background[:120])} skills' if user_background else ''}.</li>
          <li><b>🎯 What &amp; Where to Apply:</b> Build a focused {html.escape(creativity_mode)} prototype combining <i>{html.escape(title)}</i> with {html.escape(connected_titles)}.</li>
          <li><b>⚙️ Role in What You&apos;re Making:</b> Acts as the core {html.escape(category)} engine/module while the connected drops handle data ingestion or UI workflow. <i>(Add a Gemini key for live AI synthesis.)</i></li>
        </ul>
        """.strip()
        sanitized_mock = sanitize_ai_html(mock_html)
        _ideate_mem_cache[cache_key] = sanitized_mock
        return sanitized_mock

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        nodes_context = "\n".join(
            f"- {n['title'][:140]} ({n['source']}, {n['connection_reason']}, stack: {', '.join(n.get('stack_tags') or ['n/a'])})"
            for n in connected_nodes
        )

        prompt = (
            f"You are Signal's fast Idea Synthesizer. Keep your output ultra-concise (strictly 80 to 110 words total) "
            f"so it generates in 1 second.\n\n"
            f"Anchor Post: {title} ({category}) | Summary: {anchor_item.get('summary', '')[:250]}\n"
            f"Connected Nearby Drops:\n{nodes_context or 'None'}\n"
            f"User Profile: Level={education_level[:80]} | Goal={builder_goal[:80]} | Background={user_background[:150] or 'general'} | Mode={creativity_mode[:40]}\n\n"
            f"Return ONLY a single clean HTML <ul> list with EXACTLY these 4 <li> items (1-2 short sentences per bullet, no intro/outro text):\n"
            f"<li><b>🛠️ Tech Stack:</b> Exact minimal tools/languages to build this for their level.</li>\n"
            f"<li><b>📚 Prerequisites:</b> What concepts they need to know first (tailored to {education_level[:80]}).</li>\n"
            f"<li><b>🎯 What &amp; Where to Apply:</b> Concrete project idea and real-world place to use it ({creativity_mode[:40]} mode).</li>\n"
            f"<li><b>⚙️ Role in What You&apos;re Making:</b> Exact architectural role this post + the connected drops play inside the project.</li>"
        )

        response = model.generate_content(prompt)
        out = response.text.strip()
        if out.startswith("```html"):
            out = out.replace("```html", "", 1)
        elif out.startswith("```"):
            out = out.replace("```", "", 1)
        if out.endswith("```"):
            out = out.rsplit("```", 1)[0]
        cleaned = sanitize_ai_html(out.strip())
        _ideate_mem_cache[cache_key] = cleaned
        return cleaned
    except Exception as e:
        return f"<p>Failed to generate Idea Network blueprint: {html.escape(str(e)[:200])}</p>"


def chat_with_builder_ai(
    messages: list[dict],
    context_item: dict | None = None,
    user_profile: dict | None = None,
    api_key: str | None = None,
) -> str:
    """Multi-turn AI Builder Chat (XSS-sanitized output)."""
    last_user_msg = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            last_user_msg = (m.get("content") or "")[:1000]
            break

    if not api_key:
        ctx_title = ((context_item or {}).get("title") or "your project")[:150]
        return sanitize_ai_html(
            f"<p><b>[Mock Builder AI]</b> For <i>{html.escape(ctx_title)}</i>: to take your question "
            f"(&ldquo;{html.escape(last_user_msg[:80])}&rdquo;) to the next step, start by scaffolding a minimal "
            f"MVP with a single API endpoint and test it against real sample inputs. "
            f"<i>(Add your free Gemini API key in the top bar to enable live multi-turn AI chat!)</i></p>"
        )

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        ctx_block = ""
        if context_item and context_item.get("title"):
            ctx_block = (
                f"Active Story Context:\n"
                f"- Title: {str(context_item.get('title'))[:250]}\n"
                f"- URL: {str(context_item.get('url', ''))[:500]}\n"
                f"- Summary: {str(context_item.get('summary', ''))[:600]}\n"
                f"- Brainstorm Blueprint: {str(context_item.get('blueprint', ''))[:800]}\n\n"
            )

        prof = user_profile or {}
        prof_block = (
            f"User Background: Level={str(prof.get('educationLevel', 'Undergrad'))[:80]}, "
            f"Goal={str(prof.get('builderGoal', 'Project'))[:80]}, "
            f"Skills={str(prof.get('userBackground', 'general tech'))[:150]}\n\n"
        )

        history_lines = []
        for m in (messages or [])[-10:]:
            role_label = "User" if m.get("role") == "user" else "Signal AI"
            history_lines.append(f"{role_label}: {str(m.get('content', ''))[:1000]}")
        convo_text = "\n".join(history_lines)

        prompt = (
            "You are Signal's Builder AI co-pilot. Answer the user's latest message concisely, "
            "practically, and directly (under 140 words unless they ask for code). "
            "Use clean HTML (<p>, <ul>, <li>, <b>, <code>) for readability.\n\n"
            f"{ctx_block}{prof_block}"
            f"Conversation History:\n{convo_text}\n\nSignal AI:"
        )
        resp = model.generate_content(prompt)
        reply = resp.text.strip()
        if reply.startswith("```html"):
            reply = reply.replace("```html", "", 1)
        elif reply.startswith("```"):
            reply = reply.replace("```", "", 1)
        if reply.endswith("```"):
            reply = reply.rsplit("```", 1)[0]
        return sanitize_ai_html(reply.strip())
    except Exception as e:
        return f"<p>Chat error: {html.escape(str(e)[:200])}</p>"
