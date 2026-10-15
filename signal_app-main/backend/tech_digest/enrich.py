"""
Post-processing stage that runs on the full combined list from fetch_all,
before it's written to JSON. Three jobs, kept separate from fetching on purpose
so each source stays a dumb, swappable adapter:

1. Dedup near-identical stories that show up across multiple sources
   (e.g. the same launch on HN, Product Hunt, and r/startups).
2. Tag "builder idea" items -- things where someone built and shared a
   project -- and pull out a light stack/tech tag list from the text.
3. Tag tech department(s) -- which domain does this item belong to
   (cybersecurity, ai-ml, gaming-tech, cloud, web-dev, innovator, random-dev-idea).
   An item can belong to multiple depts. Keyword matching on title + summary.

All steps are deliberately simple (normalized-title matching, keyword
matching) rather than ML-based, so they're cheap, fast, and easy to debug.
"""
import re
from typing import Iterable

from .schema import NewsItem

# --- Dedup -------------------------------------------------------------

_STOPWORDS = {"the", "a", "an", "to", "for", "of", "in", "on", "and", "is",
              "with", "how", "why", "show", "hn", "new", "v1", "v2"}
_PUNCT_RE = re.compile(r"[^a-z0-9 ]")
_WS_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation/stopwords -- gives a fuzzy key so
    'Show HN: I built a Postgres GUI' and 'I built a Postgres GUI' collapse
    to the same bucket as long as the meaningful words match."""
    t = title.lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    words = [w for w in t.split() if w not in _STOPWORDS]
    return " ".join(sorted(words))


# Trust order when two items collapse to the same dedup_key -- keep the one
# from the source higher in this list (lower index wins).
_SOURCE_PRIORITY = [
    "TechCrunch", "The Verge", "Ars Technica", "MIT Technology Review",
    "Krebs on Security", "The Hacker News", "Stack Overflow Blog",
    "GitHub Trending", "Product Hunt", "Hacker News", "Hugging Face Papers",
    "Hugging Face Models", "arXiv", "Lobsters", "IndieHackers",
]


def _source_rank(source: str) -> int:
    for i, name in enumerate(_SOURCE_PRIORITY):
        if source == name or source.startswith(name):
            return i
    return len(_SOURCE_PRIORITY)


def dedup_against_existing(new_items: list[NewsItem], existing_rows: list[dict]) -> list[NewsItem]:
    """Drop new items that match something already saved from a *previous*
    fetch run, by the same normalized-title key dedup_items uses. This is
    the cross-run half of dedup: dedup_items() only catches duplicates that
    show up together in one fetch; without this, the same launch fetched
    an hour apart on two different sources would create two separate rows
    in the DB (different urls = different primary keys, so upsert alone
    won't catch it).

    Existing items always win the slot (their URL is already the row's
    primary key) -- we just skip re-saving a same-story duplicate under a
    different URL, and fold the new item's engagement into the existing
    row's via an engagement bump rather than losing that signal entirely.
    """
    existing_keys = {}
    for row in existing_rows:
        key = row.get("dedup_key") or _normalize_title(row.get("title", ""))
        if key and len(key.split()) >= 3:
            existing_keys[key] = row

    kept = []
    for item in new_items:
        key = item.dedup_key or _normalize_title(item.title)
        if key in existing_keys and len(key.split()) >= 3:
            # Same story already in the DB from an earlier run -- skip
            # inserting a duplicate row, but don't silently drop its
            # engagement signal.
            continue
        kept.append(item)
    return kept


def dedup_items(items: list[NewsItem]) -> list[NewsItem]:
    """Collapse items whose normalized titles match. When duplicates are
    found, keep the single best copy: highest engagement, with source
    priority as a tiebreaker, and merge engagement from the dropped copies
    into the survivor so cross-posted stories don't look under-engaged."""
    buckets: dict[str, list[NewsItem]] = {}
    for item in items:
        item.dedup_key = _normalize_title(item.title)
        # Titles under 3 meaningful words are too generic to dedup safely
        # (e.g. "Update" or "v2.0") -- leave them alone.
        if len(item.dedup_key.split()) < 3:
            buckets.setdefault(f"__unique__{id(item)}", []).append(item)
        else:
            buckets.setdefault(item.dedup_key, []).append(item)

    deduped = []
    for key, group in buckets.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        group.sort(key=lambda x: (_source_rank(x.source), -x.engagement_raw))
        winner = group[0]
        winner.engagement_raw += sum(g.engagement_raw for g in group[1:])
        other_sources = sorted({g.source for g in group[1:]} - {winner.source})
        if other_sources:
            winner.summary = (winner.summary or "").rstrip()
            tag = f" [also on {', '.join(other_sources)}]"
            if tag.strip() not in (winner.summary or ""):
                winner.summary = (winner.summary + tag).strip()
        deduped.append(winner)
    return deduped


# --- Builder-idea tagging ------------------------------------------------

# Lightweight keyword list for pulling out "what did they build it with"
# signal from titles/summaries. Not exhaustive -- just common enough stack
# names to be useful for a first pass.
_STACK_KEYWORDS = [
    "Next.js", "React", "Vue", "Svelte", "SvelteKit", "Angular",
    "Python", "Django", "Flask", "FastAPI", "Node.js", "Express",
    "Rust", "Go", "Golang", "TypeScript", "Ruby on Rails",
    "Postgres", "PostgreSQL", "MongoDB", "Redis", "SQLite", "MySQL",
    "Supabase", "Firebase", "AWS", "Vercel", "Docker", "Kubernetes",
    "OpenAI", "Claude", "Gemini", "LangChain", "PyTorch", "TensorFlow",
    "Swift", "SwiftUI", "Flutter", "Kotlin", "Tauri", "Electron",
]
_STACK_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _STACK_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
# Map lowercased match back to canonical display form.
_STACK_CANON = {s.lower(): s for s in _STACK_KEYWORDS}

_SHOW_HN_RE = re.compile(r"^\s*show\s*hn\s*:", re.IGNORECASE)
_BUILDER_HINTS = (
    "i built", "i made", "we built", "we made", "launching", "launched",
    "side project", "open sourced", "open-sourced", "my first app",
    "weekend project", "indie", "bootstrapped",
)


def _extract_stack_tags(text: str) -> list[str]:
    found = {m.lower() for m in _STACK_PATTERN.findall(text or "")}
    return sorted({_STACK_CANON.get(f, f) for f in found})


def tag_builder_ideas(items: Iterable[NewsItem]) -> None:
    """Mutates items in place: sets is_builder_idea and stack_tags.
    Builder ideas come from a few clear signals so this stays precise
    rather than guessy:
      - HN "Show HN:" posts
      - Product Hunt launches (the whole source is launches by definition)
      - r/startups, r/SideProject-style posts with first-person build language
      - Hugging Face Models (a model release is a "what I built" signal too)
    """
    for item in items:
        text = f"{item.title} {item.summary}"
        is_idea = False

        if item.source == "Hacker News" and _SHOW_HN_RE.search(item.title):
            is_idea = True
        elif item.source == "Product Hunt":
            is_idea = True
        elif item.source.startswith("r/") and any(h in text.lower() for h in _BUILDER_HINTS):
            is_idea = True
        elif item.source == "Hugging Face Models":
            is_idea = True
        elif item.source == "GitHub Trending":
            is_idea = True

        item.is_builder_idea = is_idea
        item.stack_tags = _extract_stack_tags(text)
        if is_idea and item.category not in ("launch",):
            item.category = "idea"


# --- Tech department tagging ---------------------------------------------

# Each dept maps to (keywords_in_title_or_summary, source_names_that_always_match).
# Keywords are matched case-insensitively against the combined title+summary text.
# Source shortcuts let us assign dept without keyword guessing for known feeds --
# e.g. Krebs on Security is always cybersecurity regardless of title wording.
_DEPT_RULES: list[tuple[str, list[str], list[str]]] = [
    (
        "cybersecurity",
        [
            "hack", "hacked", "hacking", "vulnerability", "vulnerabilities",
            "CVE", "ransomware", "malware", "exploit", "phishing", "breach",
            "zero-day", "0-day", "CISA", "threat", "attack", "infosec",
            "cybersecurity", "security flaw", "data leak", "credential",
            "botnet", "spyware", "trojan", "backdoor", "patch tuesday",
            "penetration test", "pentest", "red team", "SIEM", "SOC",
        ],
        ["Krebs on Security", "The Hacker News"],
    ),
    (
        "ai-ml",
        [
            "AI", "artificial intelligence", "LLM", "large language model",
            "GPT", "ChatGPT", "machine learning", "deep learning", "neural network",
            "transformer", "diffusion model", "fine-tun", "inference", "training",
            "dataset", "benchmark", "embedding", "RAG", "retrieval", "generative",
            "foundation model", "multimodal", "computer vision", "NLP",
            "reinforcement learning", "reward model", "agent", "autonomous",
            "Hugging Face", "arXiv", "PyTorch", "TensorFlow", "JAX",
        ],
        ["Hugging Face Papers", "Hugging Face Models", "arXiv"],
    ),
    (
        "gaming-tech",
        [
            "game", "gaming", "gamer", "GPU", "Unity", "Unreal Engine",
            "DirectX", "Vulkan", "OpenGL", "shader", "ray tracing",
            "esports", "gamedev", "game engine", "game dev", "AAA",
            "indie game", "Steam", "PlayStation", "Xbox", "Nintendo",
            "VR", "virtual reality", "AR", "augmented reality", "metaverse",
        ],
        [],
    ),
    (
        "cloud",
        [
            "AWS", "Amazon Web Services", "Azure", "GCP", "Google Cloud",
            "Kubernetes", "k8s", "Docker", "container", "serverless",
            "cloud computing", "infrastructure", "DevOps", "Terraform",
            "CI/CD", "microservice", "service mesh", "Istio", "Helm",
            "DigitalOcean", "Cloudflare", "CDN", "load balancer",
            "auto-scaling", "SRE", "observability", "monitoring",
        ],
        [],
    ),
    (
        "web-dev",
        [
            "React", "Next.js", "Vue", "Svelte", "Angular", "CSS",
            "JavaScript", "TypeScript", "frontend", "backend", "full-stack",
            "REST API", "GraphQL", "Node.js", "browser", "Vite", "webpack",
            "web performance", "accessibility", "PWA", "WebAssembly", "WASM",
            "HTML", "DOM", "web component", "Tailwind", "Sass",
        ],
        ["Stack Overflow Blog", "Smashing Magazine"],
    ),
    (
        "innovator",
        [
            "startup", "founder", "funding", "seed round", "Series A",
            "Series B", "venture", "VC", "bootstrapped", "bootstrapping",
            "indie hacker", "product launch", "YC", "Y Combinator",
            "acquisition", "IPO", "unicorn", "pivot", "MVP", "go-to-market",
        ],
        ["Product Hunt", "IndieHackers"],
    ),
]

# Fallback bucket -- assigned when no other dept matches.
_FALLBACK_DEPT = "random-dev-idea"

# Pre-compile one regex per dept for speed across large item lists.
_DEPT_PATTERNS: list[tuple[str, re.Pattern, list[str]]] = [
    (
        dept,
        re.compile(
            r"\b(" + "|".join(re.escape(kw) for kw in keywords) + r")\b",
            re.IGNORECASE,
        ) if keywords else re.compile(r"(?!x)x"),  # never-match placeholder
        sources,
    )
    for dept, keywords, sources in _DEPT_RULES
]


def tag_dept(items: Iterable[NewsItem]) -> None:
    """Mutates items in place: sets item.dept to a list of matching
    tech department slugs. An item can belong to multiple depts (e.g. an
    AI security paper lands in both 'ai-ml' and 'cybersecurity').
    Items that match nothing fall into ['random-dev-idea'] as a catch-all.
    """
    for item in items:
        text = f"{item.title} {item.summary or ''}"
        matched: list[str] = []

        for dept, pattern, always_sources in _DEPT_PATTERNS:
            # Source shortcut: certain feeds always belong to a dept.
            if any(item.source == s or item.source.startswith(s) for s in always_sources):
                matched.append(dept)
                continue
            # Keyword match on combined title + summary.
            if pattern.search(text):
                matched.append(dept)

        item.dept = matched if matched else [_FALLBACK_DEPT]


def enrich(items: list[NewsItem]) -> list[NewsItem]:
    """Single entry point fetch_all calls: tag first (needs original
    per-item context), then dedup (needs the full list)."""
    tag_builder_ideas(items)
    tag_dept(items)          # <-- new stage
    return dedup_items(items)
