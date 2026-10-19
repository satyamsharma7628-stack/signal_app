import html
import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
# google.generativeai imported lazily inside functions

_ideate_mem_cache: dict[str, str] = {}


def fetch_article_content(url: str, existing_summary: str = "") -> str:
    """Fast-scrapes the body content of the webpage (3.5s timeout, 3,500-char cap).
    If existing_summary already has substantial text (>= 220 chars), skips slow
    scraping so 50-word summaries generate 3x faster."""
    if existing_summary and len(existing_summary.strip()) >= 220:
        return existing_summary.strip()[:3500]
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=3.5)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
        text = " ".join([p for p in paragraphs if len(p) > 40])
        # 3,500 chars (~550 words) is plenty of context for a 50-word summary and
        # cuts LLM input token processing time by ~70%.
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
    if not api_key:
        mock_summary = f"""
        <p><b>[Mock Summary]</b> This 50-word Inshorts-style placeholder covers <i>{category}</i> for "{title}". It highlights the core architectural tradeoffs between throughput and state synchronization in modern distributed systems, showing how teams decouple stateful storage from stateless compute to scale reliably. <i>(Add a Gemini API key to enable live summaries.)</i></p>
        """
        return mock_summary.strip()

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
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Content:\n{content}\n\n"
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

        return summary.strip()

    except Exception as e:
        return f"<p style='color: red;'>Failed to generate summary: {e}</p>"


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

    # Scan up to 400 recent items for ultra-fast matching
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
    """Generates a fast, minimum-fluff 4-point blueprint:
    1. Tech Stack
    2. Prerequisites
    3. What & Where to Apply
    4. Role in What You're Making
    """
    title = anchor_item.get("title", "this tech drop")
    category = anchor_item.get("category", "tech")
    stacks = ", ".join(anchor_item.get("stack_tags") or []) or "Python / TypeScript / REST APIs"

    cache_key = f"{anchor_item.get('url')}|{education_level}|{builder_goal}|{user_background.strip().lower()}|{creativity_mode}|{bool(api_key)}"
    if cache_key in _ideate_mem_cache:
        return _ideate_mem_cache[cache_key]

    if not api_key:
        connected_titles = ", ".join(n["title"] for n in connected_nodes[:2]) or "recent Signal drops"
        mock_html = f"""
        <ul style="margin: 0.3rem 0; padding-left: 1.15rem; line-height: 1.55;">
          <li><b>🛠️ Tech Stack:</b> {html.escape(stacks)} (calibrated for {html.escape(builder_goal)}).</li>
          <li><b>📚 Prerequisites:</b> {html.escape(education_level)} fundamentals{f' + your {html.escape(user_background)} skills' if user_background else ''}.</li>
          <li><b>🎯 What &amp; Where to Apply:</b> Build a focused {html.escape(creativity_mode)} prototype combining <i>{html.escape(title)}</i> with {html.escape(connected_titles)}.</li>
          <li><b>⚙️ Role in What You&apos;re Making:</b> Acts as the core {html.escape(category)} engine/module while the connected drops handle data ingestion or UI workflow. <i>(Add a Gemini key for live AI synthesis.)</i></li>
        </ul>
        """.strip()
        _ideate_mem_cache[cache_key] = mock_html
        return mock_html

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        nodes_context = "\n".join(
            f"- {n['title']} ({n['source']}, {n['connection_reason']}, stack: {', '.join(n.get('stack_tags') or ['n/a'])})"
            for n in connected_nodes
        )

        prompt = (
            f"You are Signal's fast Idea Synthesizer. Keep your output ultra-concise (strictly 80 to 110 words total) "
            f"so it generates in 1 second.\n\n"
            f"Anchor Post: {title} ({category}) | Summary: {anchor_item.get('summary', '')[:250]}\n"
            f"Connected Nearby Drops:\n{nodes_context or 'None'}\n"
            f"User Profile: Level={education_level} | Goal={builder_goal} | Background={user_background or 'general'} | Mode={creativity_mode}\n\n"
            f"Return ONLY a single clean HTML <ul> list with EXACTLY these 4 <li> items (1-2 short sentences per bullet, no intro/outro text):\n"
            f"<li><b>🛠️ Tech Stack:</b> Exact minimal tools/languages to build this for their level.</li>\n"
            f"<li><b>📚 Prerequisites:</b> What concepts they need to know first (tailored to {education_level}).</li>\n"
            f"<li><b>🎯 What &amp; Where to Apply:</b> Concrete project idea and real-world place to use it ({creativity_mode} mode).</li>\n"
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
        cleaned = out.strip()
        _ideate_mem_cache[cache_key] = cleaned
        return cleaned
    except Exception as e:
        return f"<p style='color: #e08080;'>Failed to generate Idea Network blueprint: {html.escape(str(e))}</p>"


def chat_with_builder_ai(
    messages: list[dict],
    context_item: dict | None = None,
    user_profile: dict | None = None,
    api_key: str | None = None,
) -> str:
    """Multi-turn AI Builder Chat so users can continue brainstorming an idea
    with full conversation history."""
    last_user_msg = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")
            break

    if not api_key:
        ctx_title = (context_item or {}).get("title") or "your project"
        return (
            f"<b>[Mock Builder AI]</b> For <i>{html.escape(ctx_title)}</i>: to take your question "
            f"(&ldquo;{html.escape(last_user_msg[:80])}&rdquo;) to the next step, start by scaffolding a minimal "
            f"MVP with a single API endpoint and test it against real sample inputs. "
            f"<i>(Add your free Gemini API key in the sidebar to enable live multi-turn AI chat!)</i>"
        )

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        ctx_block = ""
        if context_item and context_item.get("title"):
            ctx_block = (
                f"Active Story Context:\n"
                f"- Title: {context_item.get('title')}\n"
                f"- URL: {context_item.get('url', '')}\n"
                f"- Summary: {context_item.get('summary', '')}\n"
                f"- Brainstorm Blueprint: {context_item.get('blueprint', '')}\n\n"
            )

        prof = user_profile or {}
        prof_block = (
            f"User Background: Level={prof.get('educationLevel', 'Undergrad')}, "
            f"Goal={prof.get('builderGoal', 'Project')}, "
            f"Skills={prof.get('userBackground', 'general tech')}\n\n"
        )

        history_lines = []
        for m in (messages or [])[-10:]:
            role_label = "User" if m.get("role") == "user" else "Signal AI"
            history_lines.append(f"{role_label}: {m.get('content', '')}")
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
        return reply.strip()
    except Exception as e:
        return f"<p style='color:#e08080;'>Chat error: {html.escape(str(e))}</p>"
