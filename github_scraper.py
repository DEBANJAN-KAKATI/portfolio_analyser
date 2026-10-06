"""
github_scraper.py
-----------------
Fetches the emmabostian/developer-portfolios README and parses every
portfolio entry into a structured list.

Each entry is a dict:
    {
        "name":   "Aaaabad Ahmed",
        "url":    "https://sawad.framer.website",
        "role":   "Software Engineer",   # empty string if not listed
        "letter": "A"
    }
"""

import re
import requests
from config import README_URL, SKIP_RAW_GITHUB


# Matches lines like:
#   - [Name](https://...)  [optional role text]
_ENTRY_RE = re.compile(
    r"^\s*-\s+\[([^\]]+)\]\((https?://[^)]+)\)\s*(?:\[([^\]]*)\])?\s*$",
    re.MULTILINE,
)

# Matches section headers like "## A"
_SECTION_RE = re.compile(r"^##\s+([A-Z])\s*$", re.MULTILINE)


def _is_raw_github(url: str) -> bool:
    """Return True for raw GitHub repo pages (not real portfolio sites)."""
    raw_patterns = [
        "github.com/",
        "raw.githubusercontent.com/",
    ]
    return any(p in url for p in raw_patterns)


def fetch_portfolios() -> list[dict]:
    """
    Download the README and return a list of portfolio dicts sorted by
    the name's first letter, then by name.
    """
    print(f"[github_scraper] Fetching README from {README_URL} …")
    resp = requests.get(README_URL, timeout=30)
    resp.raise_for_status()
    readme = resp.text

    # Build a map: character_position → letter, so we know which section
    # each entry belongs to.
    section_positions: list[tuple[int, str]] = [
        (m.start(), m.group(1)) for m in _SECTION_RE.finditer(readme)
    ]

    def letter_for_pos(pos: int) -> str:
        letter = "?"
        for sec_pos, sec_letter in section_positions:
            if sec_pos <= pos:
                letter = sec_letter
            else:
                break
        return letter

    portfolios: list[dict] = []
    seen_urls: set[str] = set()

    for m in _ENTRY_RE.finditer(readme):
        name = m.group(1).strip()
        url  = m.group(2).strip().rstrip('"')   # some entries have trailing "
        role = (m.group(3) or "").strip()
        letter = letter_for_pos(m.start())

        # De-duplicate
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Optionally skip raw GitHub links
        if SKIP_RAW_GITHUB and _is_raw_github(url):
            continue

        portfolios.append(
            {"name": name, "url": url, "role": role, "letter": letter}
        )

    print(f"[github_scraper] Parsed {len(portfolios)} portfolio entries.")
    return portfolios


if __name__ == "__main__":
    entries = fetch_portfolios()
    # Quick sanity check
    for e in entries[:5]:
        print(e)
    print(f"Total: {len(entries)}")
