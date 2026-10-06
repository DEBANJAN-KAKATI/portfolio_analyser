"""
progress_tracker.py
-------------------
Persists processed URLs to a JSON file so the agent can resume after
interruption without re-scraping already-done portfolios.
"""

import json
from pathlib import Path
from config import PROGRESS_FILE, RESUME


class ProgressTracker:
    def __init__(self):
        self._path = Path(PROGRESS_FILE)
        self._done: dict[str, dict] = {}   # url → {name, letter, summary}
        if RESUME and self._path.exists():
            self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._done = data
            print(
                f"[progress] Resuming — {len(self._done)} entries already done."
            )
        except Exception as exc:
            print(f"[progress] Could not load progress file: {exc}")
            self._done = {}

    def save(self) -> None:
        self._path.write_text(
            json.dumps(self._done, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def is_done(self, url: str) -> bool:
        return url in self._done

    def mark_done(
        self, url: str, name: str, letter: str, summary: str
    ) -> None:
        self._done[url] = {"name": name, "letter": letter, "summary": summary}

    def forget_letter(self, letter: str) -> None:
        """Drop all entries for *letter* so they get processed again."""
        self._done = {
            url: info for url, info in self._done.items()
            if info.get("letter") != letter
        }

    def get_summary(self, url: str) -> str:
        return self._done.get(url, {}).get("summary", "")

    def all_done(self) -> dict[str, dict]:
        return dict(self._done)

    def count(self) -> int:
        return len(self._done)
