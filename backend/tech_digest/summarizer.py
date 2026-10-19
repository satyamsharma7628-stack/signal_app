import html
import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
# google.generativeai imported lazily inside functions


def fetch_article_content(url: str) -> str:
    """Scrapes the body content of the webpage and extracts text."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
        text = " ".join([p for p in paragraphs if len(p) > 40])
        return text[:12000]
    except Exception as e:
        print(f"Scraping error for {url}: {e}")
        return ""


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
        content = fetch_article_content(url)
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
            f"Full Scraped Text Content:\n{content}\n\n"
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
    """Finds 4 connected drops from nearby days in Signal's database:
    - 2 'Direct Synergy' nodes (shared stack tags, title keywords, or same dept)
    - 2 'Cross-Pollination Bridge' nodes (high-signal builder ideas or launches from
      adjacent departments in recent days that spark mashup ideas).
    Runs in pure Python with 0 AI calls.
    """
    anchor_words = {
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9]+", anchor_title or "")
        if len(w) > 3
    }
    anchor_dept_set = set(anchor_depts or [])
    anchor_stack_set = {s.lower() for s in (anchor_stacks or [])}

    direct_candidates = []
    bridge_candidates = []

    for item in all_items:
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
                "summary": (item.get("summary") or "")[:200],
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
                "summary": (item.get("summary") or "")[:200],
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
    """Combines the anchor post + nearby connected drops + the user's education level,
    background, and chosen creativity mode into an actionable build/application blueprint."""
    title = anchor_item.get("title", "this tech drop")
    category = anchor_item.get("category", "tech")

    mode_descriptions = {
        "mashup": "Cross-Pollinate & Mashup Mode: Combine the core idea of this post with the connected nearby drops below to invent 2 original project ideas.",
        "practical": "Practical Real-World Application Mode: Show concrete places where the user can apply this technology/idea in real workflows, student projects, or products today.",
        "contrarian": "Contrarian / Niche Spin-Off Mode: Identify what existing tools or this post missed, and propose a focused niche twist that a solo builder can own.",
        "learn": "Learn-by-Building Roadmap Mode: Break down the concepts behind this post and the connected drops into a step-by-step hands-on project calibrated to the user's education level.",
    }
    mode_instruction = mode_descriptions.get(creativity_mode, mode_descriptions["mashup"])

    if not api_key:
        nodes_li = "".join(
            f"<li><b>{html.escape(n['connection_type'])}:</b> <a href='{n['url']}' target='_blank' rel='noreferrer'>{html.escape(n['title'])}</a> ({html.escape(n['source'])}) — <i>{html.escape(n['connection_reason'])}</i></li>"
            for n in connected_nodes
        )
        return f"""
        <div class="ideate-result">
          <h4>🕸️ Idea Network Blueprint ({html.escape(creativity_mode.title())} Mode)</h4>
          <p><b>Tailored for:</b> {html.escape(education_level)} · <b>Goal:</b> {html.escape(builder_goal)} {f'· <b>Skills/Interests:</b> {html.escape(user_background)}' if user_background else ''}</p>
          <p><b>How nearby drops connect to &ldquo;{html.escape(title)}&rdquo;:</b></p>
          <ul>{nodes_li or '<li>Refresh feed to load more nearby drops.</li>'}</ul>
          <p><b>Where You Can Use This:</b> Combine the core mechanism of <i>{html.escape(title)}</i> ({html.escape(category)}) with the connected drops above to build a focused prototype tailored to your {html.escape(education_level)} background. <i>(Add your free Gemini API key in the top bar to generate live AI mashup blueprints!)</i></p>
        </div>
        """.strip()

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        nodes_context = "\n".join(
            f"- [{n['connection_type']} | {n['connection_reason']}] Title: {n['title']} (Source: {n['source']}, URL: {n['url']}, Stack: {', '.join(n.get('stack_tags') or ['n/a'])})"
            for n in connected_nodes
        )

        prompt = (
            f"You are Signal's Creative Idea Network Synthesizer.\n"
            f"A user just read a 50-word summary of an article/launch and wants to discover how they can use it "
            f"and how it connects to other tech drops from nearby days.\n\n"
            f"=== ANCHOR POST ===\n"
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Departments: {', '.join(anchor_item.get('dept') or [])}\n"
            f"Stack Tags: {', '.join(anchor_item.get('stack_tags') or [])}\n"
            f"Summary: {anchor_item.get('summary', '')}\n\n"
            f"=== CONNECTED DROPS FROM NEARBY DAYS IN DATABASE ===\n"
            f"{nodes_context or 'None available'}\n\n"
            f"=== USER PROFILE & CREATIVITY SETTINGS ===\n"
            f"- Education / Experience Level: {education_level}\n"
            f"- Target Goal: {builder_goal}\n"
            f"- Personal Skills / Domain Interests: {user_background or 'General software/tech'}\n"
            f"- Selected Creativity Mode: {mode_instruction}\n\n"
            f"Write a punchy, inspiring, and highly practical response (~180 to 230 words total) formatted in clean HTML "
            f"(use only <h4>, <p>, <ul>, <li>, <b>, <a href='...' target='_blank'> tags) with these 3 short sections:\n"
            f"1. <h4>🔗 The Network Connection (Why These Drops Fit Together)</h4>: In 2 sentences, explain the creative link between the anchor post and 1-2 of the connected nearby drops above (link their titles with <a href='...'>).\n"
            f"2. <h4>💡 2 Tailored Ideas You Can Build / Apply ({creativity_mode.title()} Mode)</h4>: Give 2 concrete project or application ideas specifically calibrated to a '{education_level}' aiming for '{builder_goal}' with interests in '{user_background or 'tech'}'. Explain the exact problem it solves and why it's realistic for their level.\n"
            f"3. <h4>🛠️ Weekend Starter Stack & First Step</h4>: 1 short bullet on the simplest tech stack they should use and what to build in the first 2 hours."
        )

        response = model.generate_content(prompt)
        out = response.text.strip()
        if out.startswith("```html"):
            out = out.replace("```html", "", 1)
        elif out.startswith("```"):
            out = out.replace("```", "", 1)
        if out.endswith("```"):
            out = out.rsplit("```", 1)[0]
        return out.strip()
    except Exception as e:
        return f"<p style='color: #e08080;'>Failed to generate Idea Network blueprint: {html.escape(str(e))}</p>"
