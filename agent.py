"""
agent.py — Portfolio Analyzer Agent
=====================================
Orchestrates the full pipeline:

  1. Fetch the portfolio list from GitHub README
  2. Filter already-processed entries (resume support)
  3. Crawl each portfolio with headless Chromium: home page, its
     projects/work pages, and every individual project page
  4. Summarise each project in 2 points with AI (or heuristic fallback)
  5. Write per-letter Markdown docs + an INDEX.md

Usage:
    python agent.py                        # process all ~2000 portfolios
    python agent.py --letters A B C        # only letters A, B, C
    python agent.py --limit 20             # first 20 entries (for testing)
    python agent.py --no-resume            # ignore previous progress
"""

import argparse
import asyncio
import pathlib
import shutil
import sys
import time
from collections import defaultdict

from playwright.async_api import async_playwright

from config import CONCURRENCY, FILTER_LETTERS, OUTPUT_DIR
from github_scraper import fetch_portfolios
from portfolio_scraper import scrape_portfolios_batch
from ai_analyzer import analyse_with_ai
from docs_writer import (append_entry, init_doc, render_entry, write_index,
                         write_summary_stats)
from progress_tracker import ProgressTracker


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Portfolio Analyzer Agent")
    p.add_argument(
        "--letters", nargs="*", metavar="LETTER",
        help="Only process entries for these letters (e.g. --letters A B C)"
    )
    p.add_argument(
        "--limit", type=int, default=0,
        help="Stop after processing this many entries (0 = no limit)"
    )
    p.add_argument(
        "--no-resume", action="store_true",
        help="Ignore existing progress and start fresh"
    )
    p.add_argument(
        "--concurrency", type=int, default=CONCURRENCY,
        help=f"Parallel browser pages (default: {CONCURRENCY})"
    )
    return p.parse_args()


# ── Progress display ──────────────────────────────────────────────────────────

class AgentStats:
    def __init__(self, total: int):
        self.total     = total
        self.done      = 0
        self.scraped_ok = 0
        self.failed    = 0
        self.ai_ok     = 0
        self.heuristic = 0
        self.projects  = 0
        self.start     = time.time()

    def tick(self, scraped: bool, ai: bool, projects: int) -> None:
        self.done += 1
        self.projects += projects
        if scraped:
            self.scraped_ok += 1
        else:
            self.failed += 1
        if ai:
            self.ai_ok += 1
        else:
            self.heuristic += 1

    def eta(self) -> str:
        if self.done == 0:
            return "—"
        elapsed = time.time() - self.start
        per_item = elapsed / self.done
        remaining = (self.total - self.done) * per_item
        m, s = divmod(int(remaining), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def print_progress(self) -> None:
        if self.total == 0:
            return
        pct = self.done / self.total * 100
        bar_len = 30
        filled = int(bar_len * self.done / self.total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(
            f"\r  [{bar}] {self.done}/{self.total} ({pct:.1f}%)  "
            f"ETA: {self.eta()}   ",
            end="", flush=True,
        )

    def to_dict(self) -> dict:
        return {
            "total":      self.done,
            "scraped_ok": self.scraped_ok,
            "failed":     self.failed,
            "ai_ok":      self.ai_ok,
            "heuristic":  self.heuristic,
            "projects":   self.projects,
        }


# ── Core pipeline ─────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:

    # 1. Fetch & filter portfolio list ─────────────────────────────────────────
    all_portfolios = fetch_portfolios()

    letters_filter = set(
        lt.upper() for lt in (args.letters or FILTER_LETTERS or [])
    )
    if letters_filter:
        all_portfolios = [p for p in all_portfolios if p["letter"] in letters_filter]
        print(f"[agent] Filtered to letters {sorted(letters_filter)}: "
              f"{len(all_portfolios)} entries.")

    if args.limit and args.limit > 0:
        all_portfolios = all_portfolios[: args.limit]
        print(f"[agent] Limit set: processing first {len(all_portfolios)} entries.")

    # 2. Handle --no-resume BEFORE loading tracker ─────────────────────────────
    if args.no_resume:
        out = pathlib.Path(OUTPUT_DIR)
        if out.exists():
            shutil.rmtree(out)
        pf = pathlib.Path("progress.json")
        if pf.exists():
            pf.unlink()
        print("[agent] --no-resume: cleared output directory and progress.")

    # 3. Load progress tracker ─────────────────────────────────────────────────
    tracker = ProgressTracker()

    # 4. Initialise per-letter doc files (only if not already there) ───────────
    #    Docs from the old one-summary-per-developer table format are
    #    regenerated, so they don't mix with the new per-project sections.
    seen_letters: set[str] = set()
    for p in all_portfolios:
        letter = p["letter"]
        if letter not in seen_letters:
            doc_path = pathlib.Path(OUTPUT_DIR) / f"{letter.upper()}.md"
            if doc_path.exists() and "| # | Developer |" in doc_path.read_text(encoding="utf-8"):
                print(f"[agent] {doc_path.name} uses the old format — regenerating it.")
                tracker.forget_letter(letter)
                init_doc(letter)
            elif not doc_path.exists():
                init_doc(letter)
            seen_letters.add(letter)

    pending = [p for p in all_portfolios if not tracker.is_done(p["url"])]
    skipped = len(all_portfolios) - len(pending)
    if skipped:
        print(f"[agent] Skipping {skipped} already-processed entries.")

    # 5. Seed row counters from already-done entries ───────────────────────────
    row_counters: dict[str, int] = defaultdict(int)
    for info in tracker.all_done().values():
        row_counters[info["letter"]] += 1

    # 6. Main scrape + analyse loop ────────────────────────────────────────────
    stats = AgentStats(total=len(pending))
    print(f"\n[agent] Processing {len(pending)} portfolios "
          f"(concurrency={args.concurrency}) …\n")

    CHUNK = 10   # save progress every 10 entries

    # ── Single Playwright browser for the entire run ──────────────────────────
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        try:
            for chunk_start in range(0, max(len(pending), 1), CHUNK):
                chunk = pending[chunk_start : chunk_start + CHUNK]
                if not chunk:
                    break

                # Crawl the whole chunk concurrently
                crawls = await scrape_portfolios_batch(
                    chunk,
                    browser=browser,
                    concurrency=args.concurrency,
                )

                # Analyse & write each result sequentially
                for entry in chunk:
                    url    = entry["url"]
                    name   = entry["name"]
                    role   = entry["role"]
                    letter = entry["letter"]
                    crawl  = crawls.get(url) or {}

                    scraped_ok = bool(
                        len((crawl.get("home_text") or "").strip()) > 50
                        or crawl.get("projects")
                    )

                    projects, ai_used = analyse_with_ai(name, url, crawl)

                    row_counters[letter] += 1
                    summary = render_entry(
                        index=row_counters[letter],
                        name=name,
                        role=role,
                        url=url,
                        projects=projects,
                    )
                    append_entry(letter, summary)

                    tracker.mark_done(url, name, letter, summary)
                    stats.tick(scraped=scraped_ok, ai=ai_used,
                               projects=len(projects))
                    stats.print_progress()

                tracker.save()

        finally:
            await browser.close()

    # 7. Write index & stats ───────────────────────────────────────────────────
    print("\n\n[agent] Writing index …")
    write_index(all_portfolios)
    write_summary_stats(stats.to_dict())

    elapsed = time.time() - stats.start
    m, s = divmod(int(elapsed), 60)
    print(f"[agent] ✓ Done in {m}m {s}s.")
    print(f"        Scraped OK  : {stats.scraped_ok}")
    print(f"        Failed      : {stats.failed}")
    print(f"        Projects    : {stats.projects}")
    print(f"        AI summaries: {stats.ai_ok}")
    print(f"        Heuristic   : {stats.heuristic}")
    print(f"        Docs in     : {OUTPUT_DIR}/")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Site names contain characters the Windows console can't encode
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n\n[agent] Interrupted by user. Progress saved.")
        sys.exit(0)


if __name__ == "__main__":
    main()
