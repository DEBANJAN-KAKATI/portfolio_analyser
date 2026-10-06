# Portfolio Analyzer Agent

Scrapes every developer portfolio listed at
[emmabostian/developer-portfolios](https://github.com/emmabostian/developer-portfolios),
visits each site, opens its projects / work section and every individual
project, and writes 2 concise points per project into alphabetically
organised Markdown docs.

---

## Output

All docs are saved to the **`portfolio_docs/`** folder inside this directory:

```
portfolio_docs/
  INDEX.md   ← master index with entry counts & links to each letter
  A.md       ← all "A" developers
  B.md
  C.md
  ...
  Z.md
```

Each developer gets a compact section with **2 points for every project**
the agent finds (it opens the portfolio's projects/work page and then each
project's own page — case study, GitHub repo or live demo):

```markdown

## Setup (one-time)

```powershell
# 1. Install Python dependencies
pip install playwright google-generativeai openai requests beautifulsoup4

# 2. Install the headless browser
python -m playwright install chromium
```

---

## Configuration

Open **`config.py`** and fill in two things:

### 1. Choose your AI provider

```python
AI_PROVIDER = "gemini"    # ← "gemini"  (free)  or  "openai"  (paid)
```

### 2. Paste your API key

**Gemini (free tier — recommended)**
Get a free key at → https://aistudio.google.com/app/apikey

```python
GEMINI_API_KEY = "AIza..."          # paste here
GEMINI_MODEL   = "gemini-2.0-flash" # free & fast
```

**OpenAI (paid)**
Get a key at → https://platform.openai.com/api-keys

```python
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL   = "gpt-4o-mini"
```

> **No key?** Leave both blank. The agent still runs using a built-in
> heuristic extractor — summaries will be less polished but still useful.

---

## How to run

Open a terminal in this folder (`d:\New folder\AI_Agents\portfolio-analyzer`)
and run:

```powershell
# ── Process ALL ~2000 portfolios ──────────────────────────────────────────
python agent.py

# ── Only specific letters (faster for testing) ────────────────────────────
python agent.py --letters A B C

# ── First N entries only ──────────────────────────────────────────────────
python agent.py --limit 20

# ── Start completely fresh (ignore previous progress) ─────────────────────
python agent.py --no-resume

# ── Combine flags ─────────────────────────────────────────────────────────
python agent.py --letters A --limit 50 --no-resume
```

### Resume support

The agent saves progress to `progress.json` after every 50 entries.
If you stop it (`Ctrl+C`) and run it again **without** `--no-resume`,
it will skip everything already done and continue from where it left off.

---

## Tips

| Goal | What to do |
|------|-----------|
| Run faster | Increase `CONCURRENCY` in `config.py` (try 5 on a fast connection) |
| Only certain letters | Set `FILTER_LETTERS = ["A","B"]` in `config.py` |
| Change output folder | Set `OUTPUT_DIR = "my_folder"` in `config.py` |
| Switch AI at any time | Change `AI_PROVIDER` in `config.py` and re-run |

---

## Project files

```
agent.py            ← main orchestrator (run this)
config.py           ← all settings (edit this)
github_scraper.py   ← parses the GitHub README portfolio list
portfolio_scraper.py← visits each site with headless Chromium
ai_analyzer.py      ← calls Gemini / OpenAI / heuristic
docs_writer.py      ← writes the per-letter Markdown files
progress_tracker.py ← saves/loads progress.json for resume
portfolio_docs/     ← OUTPUT: generated docs live here
progress.json       ← resume checkpoint (auto-managed)
```
