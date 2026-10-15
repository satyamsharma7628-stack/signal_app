import requests
import re
from bs4 import BeautifulSoup
import google.generativeai as genai


def fetch_article_content(url: str) -> str:
    """Scrapes the body content of the webpage and extracts text."""
    try:
        # User agent to bypass basic protection
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Get paragraphs
        paragraphs = [p.get_text().strip() for p in soup.find_all("p")]
        text = " ".join([p for p in paragraphs if len(p) > 40])

        # Limit to first 12,000 characters to keep context size reasonable
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
        # Fallback Mock Summary Builder (~50 words, Inshorts style)
        mock_summary = f"""
        <p><b>[Mock Summary]</b> This 50-word Inshorts-style placeholder covers <i>{category}</i> for "{title}". It highlights the core architectural tradeoffs between throughput and state synchronization in modern distributed systems, showing how teams decouple stateful storage from stateless compute to scale reliably. <i>(Add a Gemini API key to enable live summaries.)</i></p>
        """
        return mock_summary.strip()

    try:
        # Fetch the real web page content
        content = fetch_article_content(url)
        if not content:
            content = f"Title: {title}. Context summary: {existing_summary}"

        # Configure Gemini
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

        # Clean potential markdown block formatting from the Gemini response if any
        if summary.startswith("```html"):
            summary = summary.replace("```html", "", 1)
        elif summary.startswith("```"):
            summary = summary.replace("```", "", 1)
        if summary.endswith("```"):
            summary = summary.rsplit("```", 1)[0]

        return summary.strip()

    except Exception as e:
        return f"<p style='color: red;'>Failed to generate summary: {e}</p>"