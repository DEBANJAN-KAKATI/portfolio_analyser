"""
ai_analyzer.py
--------------
Turns a crawled portfolio (home page + project pages) into a list of
projects, each with a 2-bullet summary.

Supported providers (set AI_PROVIDER in config.py):
  "gemini"  — Google Gemini        (free tier: ~1500 req/day)
  "openai"  — OpenAI ChatGPT       (paid)
  "claude"  — Anthropic Claude     (paid)
  ""        — No AI; uses built-in heuristic extractor

Keys can be set in config.py or as environment variables:
  GEMINI_API_KEY / OPENAI_API_KEY / CLAUDE_API_KEY (or ANTHROPIC_API_KEY)

Public entry point:
    analyse_with_ai(name, url, crawl) -> (projects, used_ai)
    projects = [{"name": "NajmAI", "url": "https://…", "bullets": ["…", "…"]}, …]
"""

import json
import os
import re
import time
import textwrap

from config import (
    AI_PROVIDER,
    GEMINI_API_KEY, GEMINI_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    CLAUDE_API_KEY, CLAUDE_MODEL,
    AI_CALL_DELAY,
)

# Upper bound on characters sent to the AI for one portfolio
_PROMPT_CHARS = 24000
_MAX_OUTPUT_TOKENS = 3000


# ── Shared prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
    You are a technical analyst summarising the projects in a software
    developer's portfolio. You receive text crawled from the portfolio:
    the home page, its projects/work pages, and a list of PROJECT
    CANDIDATES (each with card text and, when available, text from the
    project's own page — a case study, GitHub README or live site).

    Produce a summary of EVERY distinct project the developer built.

    Rules:
    - Include every real project: apps, websites, templates, tools,
      libraries, games, ML models, client work, open-source repos.
    - Skip candidates that are not projects: navigation/CTA links, blog
      posts, tools the developer merely uses, social profiles, employers.
    - If the candidate list is empty or incomplete, find projects in the
      page text yourself.
    - Use the project's real name (strip numbering like "01").
    - Exactly 2 bullets per project, each one sentence, max 25 words:
        bullet 1 — what it is / what it does;
        bullet 2 — how it was built (tech stack) or a notable feature/result.
    - Base everything on the given text; do not invent technologies.
    - Keep projects in the order they appear.

    Reply with JSON only, no markdown fences:
    {"projects": [{"name": "...", "candidate": <candidate number or null>,
                   "bullets": ["...", "..."]}]}
    If there are no projects at all, reply {"projects": []}.
""").strip()


def _build_user_message(name: str, url: str, crawl: dict) -> str:
    parts = [f"Developer: {name}", f"Portfolio URL: {url}", ""]

    candidates = crawl.get("projects") or []
    cand_lines = []
    for i, p in enumerate(candidates, 1):
        block = [f"[{i}] Title: {p['title']}", f"    Link: {p['url']}"]
        if p.get("card_text"):
            block.append(f"    Card text: {p['card_text'][:500]}")
        if p.get("detail_text"):
            block.append(f"    Project page text: {p['detail_text']}")
        cand_lines.append("\n".join(block))
    cand_section = "\n\n".join(cand_lines) or "(none found)"

    # Candidates are the most valuable part: give them the bulk of the budget
    budget = _PROMPT_CHARS - len(cand_section)
    home  = (crawl.get("home_text") or "")[: max(1500, budget // 2)]
    index = (crawl.get("index_text") or "")[: max(1500, budget // 2)]

    parts += [
        "=== HOME PAGE ===", home or "(empty)", "",
        "=== PROJECTS / WORK PAGES ===", index or "(none)", "",
        "=== PROJECT CANDIDATES ===", cand_section,
    ]
    return "\n".join(parts)[: _PROMPT_CHARS + 6000]


# ── Provider clients ──────────────────────────────────────────────────────────

def _call_gemini(user_msg: str) -> str | None:
    key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    return response.text


def _call_openai(user_msg: str) -> str | None:
    key = OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None
    from openai import OpenAI

    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        max_tokens=_MAX_OUTPUT_TOKENS,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _call_claude(user_msg: str) -> str | None:
    key = (CLAUDE_API_KEY or os.getenv("CLAUDE_API_KEY", "")
           or os.getenv("ANTHROPIC_API_KEY", ""))
    if not key:
        return None
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


_PROVIDERS = {"gemini": _call_gemini, "openai": _call_openai, "claude": _call_claude}


# ── Public entry point ────────────────────────────────────────────────────────

def analyse_with_ai(name: str, url: str, crawl: dict) -> tuple[list[dict], bool]:
    """
    Return (projects, used_ai) for this developer.

    Tries the configured AI_PROVIDER first; falls back to the heuristic
    if the key is missing or the API call fails.
    """
    call = _PROVIDERS.get(AI_PROVIDER.strip().lower())
    if call:
        try:
            raw = call(_build_user_message(name, url, crawl))
            if raw is not None:
                if AI_CALL_DELAY > 0:
                    time.sleep(AI_CALL_DELAY)
                projects = _parse_ai_json(raw, crawl.get("projects") or [])
                if projects is not None:
                    return projects, True
                print(f"\n  [ai_analyzer] Unparseable AI reply for {name}; using heuristic.")
        except Exception as exc:
            print(f"\n  [ai_analyzer] {AI_PROVIDER} error for {name}: {exc}")

    return _heuristic_projects(crawl), False


def _parse_ai_json(raw: str, candidates: list[dict]) -> list[dict] | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    by_title = {_norm(c["title"]): c for c in candidates}
    projects = []
    for item in data.get("projects", []):
        pname = str(item.get("name", "")).strip()
        bullets = [str(b).strip().lstrip("•-* ").strip()
                   for b in item.get("bullets", []) if str(b).strip()]
        if not pname or not bullets:
            continue
        # attach the project link when we can match it to a candidate
        cand = None
        idx = item.get("candidate")
        if isinstance(idx, int) and 1 <= idx <= len(candidates):
            cand = candidates[idx - 1]
        cand = cand or by_title.get(_norm(pname))
        projects.append({
            "name": pname,
            "url": cand["url"] if cand else "",
            "bullets": bullets[:2],
        })
    return projects


# ── Heuristic fallback (no API needed) ───────────────────────────────────────

_TECH_WORDS = [
    "React", "Next.js", "Vue", "Nuxt", "Angular", "Svelte", "Astro", "Node.js",
    "Express", "NestJS", "Django", "Flask", "FastAPI", "Spring", "Laravel",
    "Rails", "ASP.NET", ".NET", "Python", "TypeScript", "JavaScript", "Go",
    "Rust", "Java", "Kotlin", "Swift", "Flutter", "React Native", "Dart",
    "C++", "C#", "PHP", "Ruby", "Tailwind", "MongoDB", "PostgreSQL", "MySQL",
    "Firebase", "Supabase", "Redis", "GraphQL", "Docker", "Kubernetes", "AWS",
    "GCP", "Azure", "TensorFlow", "PyTorch", "OpenAI", "LangChain", "Streamlit",
    "Framer", "Figma", "Three.js", "Solidity", "Unity", "Electron",
]
_TECH_RE = re.compile(
    r"(?<![.0-9A-Z])(" + "|".join(re.escape(t) for t in _TECH_WORDS) + r")(?![\w])"
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_JUNK_RE = re.compile(
    r"^(view|live|demo|github|source|code|read more|play|visit|open|"
    r"view app|case study|learn more|\d+)$",
    re.I,
)


def _norm(s: str) -> str:
    s = re.sub(r"^\s*\d{1,2}[\s.)\-]+", "", s or "")
    return re.sub(r"\W+", " ", s).strip().lower()


def _sentences(text: str, skip: str) -> list[str]:
    out = []
    for s in _SENT_SPLIT_RE.split(text or ""):
        s = s.strip(" •-–|")
        if (len(s.split()) < 4 or _JUNK_RE.match(s) or "Last commit" in s
                or _norm(s) == _norm(skip) or s.lower().startswith(("page title", "meta"))):
            continue
        words = s.split()
        out.append(" ".join(words[:25]) + ("…" if len(words) > 25 else ""))
    return out


def _heuristic_projects(crawl: dict) -> list[dict]:
    projects = []
    for p in crawl.get("projects") or []:
        title = re.sub(r"^\s*\d{1,2}[\s.)\-]+", "", p["title"]).strip() or p["title"]
        card = p.get("card_text", "")
        # remove the title from the card text so it isn't repeated
        card = card.replace(p["title"], " ", 1).strip()
        sents = _sentences(card, title) + _sentences(p.get("detail_text", ""), title)
        sents = list(dict.fromkeys(sents))
        tech = list(dict.fromkeys(_TECH_RE.findall(card + " " + p.get("detail_text", ""))))

        b1 = sents[0] if sents else (card[:150] or "Project listed on the portfolio.")
        if tech:
            b2 = "Built with " + ", ".join(tech[:6]) + "."
        elif len(sents) > 1:
            b2 = sents[1]
        else:
            b2 = "No further details on the project page."
        projects.append({"name": title, "url": p["url"], "bullets": [b1, b2]})

    if projects:
        return projects

    # No project links found: summarise the home page as a single entry
    text = (crawl.get("home_text") or "") + "\n" + (crawl.get("index_text") or "")
    sents = _sentences(text, "")
    if not sents:
        return []
    return [{
        "name": "Portfolio overview (no project pages found)",
        "url": "",
        "bullets": sents[:2] if len(sents) > 1 else [sents[0], "Visit the site for details."],
    }]
