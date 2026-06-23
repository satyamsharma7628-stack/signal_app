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

def summarize_article(url: str, title: str, category: str, existing_summary: str, api_key: str | None = None) -> str:
    """Generates a 300-500 words summary using Gemini or fallback mock."""
    if not api_key:
        # Fallback Mock Summary Builder
        mock_summary = f"""
        <h3>[Mock Summary] {title}</h3>
        <p>This is a detailed mock analysis of the article. Since no Gemini API Key is configured in the sidebar, this realistic 300 to 500 words placeholder demonstrates the lazy-loading architecture and summarization UI.</p>
        <p><b>Technical Breakdown:</b> The topic relates to <i>{category}</i>. In tech ecosystems, issues surrounding integration, scalability, and performance are paramount. We simulate a deeper dive into the architecture: typically, systems employing these methodologies experience a 2x throughput optimization but introduce higher complexity in state synchronization. Developers frequently struggle with handling concurrent updates, particularly under high network latency constraints.</p>
        <p><b>Key Takeaways:</b></p>
        <ul>
            <li><b>Performance Tradeoffs:</b> Enhancing horizontal scaling often requires trading consistency for availability.</li>
            <li><b>Integration Complexity:</b> Adopting new frameworks requires robust data sanitization layers.</li>
            <li><b>Scalability Guidelines:</b> Decoupling stateful layers from stateless execution remains the standard recommendation for distributed systems in this domain.</li>
        </ul>
        <p><i>Real AI summaries aren't enabled on this server yet — set GEMINI_API_KEY in the backend environment to turn them on.</i></p>
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
            f"You are a professional tech researcher and editor. Write a comprehensive, highly informative "
            f"summary between 300 and 500 words of the following article.\n\n"
            f"Title: {title}\n"
            f"Category: {category}\n"
            f"Full Scraped Text Content:\n{content}\n\n"
            f"Ensure the summary details the core technological details, architecture, findings, key claims, "
            f"and overall significance. Use clean HTML tags (such as <h3>, <p>, <ul>, <li>, <b>) to format the output nicely."
        )
        
        response = model.generate_content(prompt)
        summary = response.text.strip()
        
        # Clean potential markdown block formatting from the Gemini response if any
        if summary.startswith("```html"):
            summary = summary.replace("```html", "", 1)
        if summary.endswith("```"):
            summary = summary.rsplit("```", 1)[0]
            
        return summary.strip()
        
    except Exception as e:
        return f"<p style='color: red;'>Failed to generate summary: {e}</p>"
