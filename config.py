"""
Central configuration for the Portfolio Analyzer Agent.
Edit the values in this file before running.
"""

# ── AI Provider ───────────────────────────────────────────────────────────────
#
#   Pick ONE provider and paste the matching API key below.
#
#   "gemini"  → Google Gemini   (free tier ~1500 req/day)
#   "openai"  → OpenAI ChatGPT  (paid)
#   "claude"  → Anthropic Claude (paid)
#   ""        → no AI; uses built-in heuristic extractor (no key needed)
#
AI_PROVIDER = "gemini"       # ← change to "openai" or "claude" if preferred

# ── Gemini settings ───────────────────────────────────────────────────────────
# Free key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = ""          # e.g. "AIza..."  OR set env var GEMINI_API_KEY
GEMINI_MODEL   = "gemini-2.0-flash"   # fast & free-tier friendly

# ── OpenAI settings ───────────────────────────────────────────────────────────
# Key: https://platform.openai.com/api-keys
OPENAI_API_KEY = ""          # e.g. "sk-..."   OR set env var OPENAI_API_KEY
OPENAI_MODEL   = "gpt-4o-mini"

# ── Claude (Anthropic) settings ───────────────────────────────────────────────
# Key: https://console.anthropic.com/settings/keys
CLAUDE_API_KEY = ""          # e.g. "sk-ant-..." OR set env var CLAUDE_API_KEY
CLAUDE_MODEL   = "claude-haiku-4-5"  # fast & cost-effective

# ── Source ────────────────────────────────────────────────────────────────────
README_URL = (
    "https://raw.githubusercontent.com/emmabostian/"
    "developer-portfolios/master/README.md"
)

# ── Output ────────────────────────────────────────────────────────────────────
# All generated docs (A.md … Z.md + INDEX.md) go into this folder.
OUTPUT_DIR = "portfolio_docs"

# ── Scraping behaviour ────────────────────────────────────────────────────────
# Max simultaneous browser pages. Keep at 3 on Windows; raise to 5+ on Linux.
CONCURRENCY = 3

# Seconds before a page load is abandoned.
PAGE_TIMEOUT = 12

# Max characters of page text sent to the AI (controls token cost).
MAX_TEXT_CHARS = 6000

# ── Project crawling ──────────────────────────────────────────────────────────
# Max projects recorded per portfolio.
MAX_PROJECTS = 25

# Max project pages (case study / GitHub repo / live demo) opened per portfolio.
MAX_DETAIL_PAGES = 15

# Characters kept from each project page.
DETAIL_TEXT_CHARS = 1500

# Project pages opened in parallel for one portfolio.
DETAIL_CONCURRENCY = 3

# Hard cap (seconds) on crawling one portfolio including its project pages.
PORTFOLIO_TIMEOUT = 120

# Skip entries whose URL is a raw GitHub repo page (not a portfolio website).
SKIP_RAW_GITHUB = True

# ── Resume ────────────────────────────────────────────────────────────────────
# Set to True to skip already-processed entries on the next run.
RESUME = True
PROGRESS_FILE = "progress.json"

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Extra delay (seconds) between AI API calls. 0 = no delay.
AI_CALL_DELAY = 0.2

# ── Letter filter ─────────────────────────────────────────────────────────────
# Process only these letters. Empty list = process all 26 letters.
# Example: FILTER_LETTERS = ["A", "B", "C"]
FILTER_LETTERS = []

# ── Local secrets ─────────────────────────────────────────────────────────────
# Put your real API keys in config_local.py (git-ignored, never pushed), e.g.
#     GEMINI_API_KEY = "AIza..."
# Anything defined there overrides the values above.
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
