"""
portfolio_scraper.py
--------------------
Crawls a developer's portfolio with headless Chromium and collects every
project it can find:

  1. Open the home page, scroll through it, grab text + all links.
  2. Follow links to "projects / work / portfolio" index pages (e.g. /projects).
  3. Collect project cards (title, card text, links) from those pages.
  4. Open each project's own page (case study, GitHub repo, live demo)
     and grab its main text.

Key design: the caller owns the Browser instance and passes it in.
This avoids re-entering async_playwright() inside an existing event loop
(which deadlocks on Windows).

Typical usage from agent.py:

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        results = await scrape_portfolios_batch(entries, browser, concurrency=3)
        await browser.close()

Each result is a dict:
    {
        "home_text":  "...",        # home page text
        "index_text": "...",        # text of /projects-style pages
        "projects":   [ {"title", "url", "links", "card_text", "detail_text"} ],
    }
"""

import asyncio
import re
import time
from urllib.parse import urlparse, urldefrag

from playwright.async_api import async_playwright, Browser, BrowserContext

from config import (
    PAGE_TIMEOUT, MAX_TEXT_CHARS,
    MAX_PROJECTS, MAX_DETAIL_PAGES, DETAIL_TEXT_CHARS,
    DETAIL_CONCURRENCY, PORTFOLIO_TIMEOUT,
)

# ── Constants ─────────────────────────────────────────────────────────────────

# First path segment of a page that lists projects  (/projects, /work, …)
_INDEX_SEG_RE = re.compile(
    r"^(projects?|works?|my-?works?|portfolio|case-?stud(y|ies)|showcase|"
    r"creations|builds|apps|products|lab|playground|selected-work)$",
    re.I,
)
# Link text that points to a project listing ("Projects", "View all work" …)
_INDEX_TEXT_RE = re.compile(
    r"^((view|see|explore|browse)\s+(all\s+)?(my\s+)?|all\s+|more\s+|my\s+)?"
    r"(projects?|works?|portfolio|case stud(y|ies))\b",
    re.I,
)
# Same-site project detail pages  (/projects/foo, /work/bar, /case-study/baz)
_DETAIL_PATH_RE = re.compile(
    r"^/(projects?|works?|portfolio|case-?stud(y|ies)|showcase|apps?|builds?|"
    r"creations|products)/[^/]+",
    re.I,
)
# Same-site pages that are never projects
_NON_PROJECT_SEGS = {
    "", "about", "contact", "resume", "cv", "blog", "blogs", "posts", "post",
    "articles", "writing", "thoughts", "notes", "skills", "experience",
    "services", "tools", "uses", "now", "home", "privacy", "terms", "tags",
    "categories", "newsletter", "talks", "testimonials", "pricing", "login",
}
# External sites that are profiles/socials, not projects
_SOCIAL_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com",
    "dribbble.com", "behance.net", "medium.com", "dev.to", "hashnode.",
    "youtube.com", "youtu.be", "tiktok.com", "threads.net", "discord.",
    "t.me", "wa.me", "calendly.com", "cal.com", "buymeacoffee.com",
    "ko-fi.com", "patreon.com", "stackoverflow.com", "leetcode.com",
    "hackerrank.com", "codepen.io/", "google.com/maps", "reddit.com",
    "vercel.com", "netlify.com", "render.com",
)
# External links worth listing as a project but not worth opening
_NO_VISIT_HOSTS = ("framer.link", "framer.com", "figma.com", "webflow.com")
# Call-to-action link titles that are never project names
_CTA_TITLE_RE = re.compile(
    r"^(use|get|view|see|explore|browse|visit|read|learn|more|want|create|"
    r"download|buy|contact|hire|let'?s|start|book|check|go|back|click|made in)\b",
    re.I,
)
_SKIP_EXT_RE = re.compile(r"\.(pdf|docx?|pptx?|zip|png|jpe?g|gif|svg|webp|mp4|mp3)$", re.I)

# JS run inside the page: returns every <a> with its surrounding "card".
_COLLECT_LINKS_JS = r"""
() => {
  const KW = /project|work|portfolio|showcase|case[-_\s]?stud|creation|featured|selected|built/i;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const firstLine = s => ((s || '').split('\n').map(x => x.trim()).find(x => x.length > 1) || '');
  const HEAD = 'h1,h2,h3,h4,h5,h6,[class*="title" i],[class*="name" i]';

  const sectionHint = a => {
    let el = a.parentElement;
    for (let i = 0; i < 10 && el && el !== document.body; i++, el = el.parentElement) {
      const attrs = [el.id, typeof el.className === 'string' ? el.className : '',
                     el.getAttribute('aria-label') || ''].join(' ');
      if (KW.test(attrs) && !/framework|network|homework|workflow/i.test(attrs)) return true;
      if (el.tagName === 'SECTION' || el.tagName === 'ARTICLE') {
        const h = el.querySelector('h1,h2,h3');
        if (h && KW.test(h.innerText || '')) return true;
      }
    }
    return false;
  };

  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const inNav = !!a.closest('nav, header, footer');
    // climb up to the smallest ancestor that looks like a card
    // (stop before an ancestor that holds several cards: another link with
    //  its own text, i.e. a sibling card, or too many links overall)
    let card = a, el = a;
    for (let i = 0; i < 5 && el && el !== document.body; i++, el = el.parentElement) {
      const t = clean(el.innerText);
      if (t.length > 1200) break;
      if (el !== a) {
        const others = [...el.querySelectorAll('a[href]')].filter(x => x.href !== a.href);
        if (others.some(x => !x.contains(a) && clean(x.innerText).length > 15)) break;
        if (new Set(others.map(x => x.href)).size > 3) break;
      }
      card = el;
      if (t.length >= 30 && el.querySelector(HEAD)) break;
    }
    const h = card.querySelector(HEAD);
    const title = clean(h ? h.innerText : '') || clean(firstLine(a.innerText)) ||
                  clean(a.getAttribute('aria-label') || a.title || '');
    out.push({
      href: a.href,
      text: clean(a.innerText || a.getAttribute('aria-label') || ''),
      title: title.slice(0, 100),
      card: clean(card.innerText).slice(0, 600),
      nav: inNav,
      section: sectionHint(a),
    });
  }
  return out;
}
"""

# JS: main readable text of a project detail page
_MAIN_TEXT_JS = r"""
() => {
  if (location.hostname === 'github.com') {
    // Repo "About" blurb + README (skip the file-listing table)
    const about = document.querySelector('.Layout-sidebar p.f4, [itemprop="about"]');
    const readme = document.querySelector('article.markdown-body');
    const t = [about && about.innerText, readme && readme.innerText]
      .filter(Boolean).join('\n');
    if (t.trim()) return t;
  }
  const pick = document.querySelector(
    'article.markdown-body, #readme article, article, main, [role="main"]');
  const el = pick && (pick.innerText || '').trim().length > 80 ? pick : document.body;
  return el ? el.innerText : '';
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _same_site(a: str, b: str) -> bool:
    ha, hb = _host(a), _host(b)
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def _first_seg(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[0].lower() if path else ""


def _is_github_repo(url: str) -> bool:
    p = urlparse(url)
    if _host(url) != "github.com":
        return False
    parts = [x for x in p.path.split("/") if x]
    return len(parts) >= 2 and parts[0] not in {"orgs", "sponsors", "topics", "features"}


def _clean_text(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


def _is_index_link(link: dict, home: str) -> bool:
    href = link["href"]
    if not _same_site(href, home):
        return False
    path = urlparse(href).path.strip("/")
    if path.count("/") > 0:
        return False
    if _INDEX_SEG_RE.match(path):
        return True
    return bool(path) and bool(_INDEX_TEXT_RE.match(link["text"]))


def _is_project_link(link: dict, page_url: str, home: str, on_index_page: bool) -> bool:
    href = link["href"]
    if not href.startswith("http") or _SKIP_EXT_RE.search(urlparse(href).path):
        return False
    base, _ = urldefrag(href)
    page_base, _ = urldefrag(page_url)
    if base.rstrip("/") == page_base.rstrip("/"):        # in-page #anchor
        return False
    host = _host(href)
    if any(s in host or s in href for s in _SOCIAL_HOSTS):
        return False

    title = link["title"] or link["text"]
    if re.fullmatch(r"(\w ){2,}\w", title):               # "M o r e  T e m p l a t e s"
        title = title.replace(" ", "")
    if _CTA_TITLE_RE.match(title) or title.lower().startswith(("moretemplates", "viewall")):
        return False
    if any(h in host for h in _NO_VISIT_HOSTS) and urlparse(href).path.strip("/") == "":
        return False                                      # "Made in Framer" badges etc.

    if _same_site(href, home):
        if _is_index_link(link, home):                    # /projects itself
            return False
        if _DETAIL_PATH_RE.match(urlparse(href).path):
            return True
        if _first_seg(href) in _NON_PROJECT_SEGS or link["nav"]:
            return False
        # other same-site pages only count inside a project section
        return link["section"] and len(link["card"]) >= 30

    # external link
    if host == "github.com" and not _is_github_repo(href):
        return False                                      # profile page
    if link["nav"]:
        return False
    if _is_github_repo(href):
        return link["section"] or on_index_page or len(link["card"]) >= 30
    return (link["section"] or on_index_page) and len(link["card"]) >= 20


def _visit_priority(url: str, home: str) -> int:
    """Lower is better: own case-study page > GitHub repo > live demo."""
    if _same_site(url, home):
        return 0
    if _is_github_repo(url):
        return 1
    if any(h in _host(url) for h in _NO_VISIT_HOSTS):
        return 9
    return 2


# ── Page loading ──────────────────────────────────────────────────────────────

async def _open(context: BrowserContext, url: str, scroll: bool = True):
    page = await context.new_page()
    await page.goto(url, timeout=PAGE_TIMEOUT * 1000, wait_until="domcontentloaded")
    await asyncio.sleep(1.2)
    if scroll:
        # Scroll step by step so lazy-loaded / scroll-animated cards render
        try:
            for _ in range(12):
                at_bottom = await page.evaluate(
                    "() => { window.scrollBy(0, window.innerHeight);"
                    " return window.innerHeight + window.scrollY"
                    " >= document.body.scrollHeight - 5; }"
                )
                await asyncio.sleep(0.15)
                if at_bottom:
                    break
        except Exception:
            pass
        await asyncio.sleep(0.3)
    return page


async def _read_listing_page(context: BrowserContext, url: str) -> tuple[str, str, list[dict]]:
    """Return (final_url, body_text, links) for a home/index page."""
    page = await asyncio.wait_for(_open(context, url), timeout=PAGE_TIMEOUT + 8)
    try:
        final_url = page.url
        text = await page.inner_text("body")
        try:
            title = await page.title()
            desc = await page.get_attribute('meta[name="description"]', "content",
                                            timeout=1000)
            text = f"Page title: {title}\nMeta description: {desc or ''}\n\n{text}"
        except Exception:
            pass
        links = await page.evaluate(_COLLECT_LINKS_JS)
        return final_url, text, links
    finally:
        await page.close()


async def _read_detail_page(context: BrowserContext, url: str) -> str:
    async def _go() -> str:
        page = await _open(context, url, scroll=False)
        try:
            return await page.evaluate(_MAIN_TEXT_JS)
        finally:
            await page.close()
    try:
        text = await asyncio.wait_for(_go(), timeout=PAGE_TIMEOUT + 5)
        return _clean_text(text, DETAIL_TEXT_CHARS)
    except Exception:
        return ""


# ── Portfolio crawler ─────────────────────────────────────────────────────────

def _add_projects(found: dict, links: list[dict], page_url: str, home: str,
                  on_index_page: bool) -> None:
    """Merge project-looking links into *found* (keyed by lower-case title)."""
    for link in links:
        if not _is_project_link(link, page_url, home, on_index_page):
            continue
        href, _ = urldefrag(link["href"])
        title = (link["title"] or link["text"][:60]
                 or urlparse(href).path.rstrip("/").split("/")[-1] or _host(href))
        key = re.sub(r"\W+", " ", title).strip().lower()
        if not key:
            continue
        proj = found.get(key)
        if proj is None:
            # same link already recorded under another title?
            proj = next((p for p in found.values() if href in p["links"]), None)
        if proj is None:
            if len(found) >= MAX_PROJECTS:
                continue
            proj = found[key] = {"title": title, "links": [], "card_text": "",
                                 "detail_text": ""}
        if href not in proj["links"]:
            proj["links"].append(href)
        if len(link["card"]) > len(proj["card_text"]):
            proj["card_text"] = link["card"]


async def _crawl(url: str, browser: Browser, result: dict) -> None:
    """Fill *result* in place so partial data survives a timeout."""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        java_script_enabled=True,
        ignore_https_errors=True,
    )
    # Skip heavy assets — we only need text
    await context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "media", "font"}
        else route.continue_(),
    )
    try:
        # 1. Home page
        home, home_text, home_links = await _read_listing_page(context, url)
        result["home_text"] = _clean_text(home_text, MAX_TEXT_CHARS)

        found: dict[str, dict] = {}
        _add_projects(found, home_links, home, home, on_index_page=False)

        # 2. Projects / work index pages  (/projects, /works, …)
        index_urls: list[str] = []
        for link in home_links:
            href, _ = urldefrag(link["href"])
            if (_is_index_link(link, home) and href not in index_urls
                    and href.rstrip("/") != home.rstrip("/")):
                index_urls.append(href)
        index_texts: list[str] = []
        for idx_url in index_urls[:2]:
            try:
                final, text, links = await _read_listing_page(context, idx_url)
            except Exception:
                continue
            index_texts.append(f"[{final}]\n{_clean_text(text, MAX_TEXT_CHARS)}")
            _add_projects(found, links, final, home, on_index_page=True)
        result["index_text"] = "\n\n".join(index_texts)

        # 3. Visit each project's own page
        projects = list(found.values())
        for p in projects:
            p["links"].sort(key=lambda u: _visit_priority(u, home))
            p["url"] = p["links"][0]
        result["projects"] = projects

        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def _detail(p: dict) -> None:
            if _visit_priority(p["url"], home) >= 9:
                return
            async with sem:
                p["detail_text"] = await _read_detail_page(context, p["url"])

        await asyncio.gather(*[_detail(p) for p in projects[:MAX_DETAIL_PAGES]])
    finally:
        try:
            await context.close()
        except Exception:
            pass


async def scrape_portfolio(url: str, browser: Browser) -> dict:
    """
    Crawl *url* and return {"home_text", "index_text", "projects"}.
    A hard wall-clock cap (PORTFOLIO_TIMEOUT) stops one slow site from
    blocking the batch; whatever was collected before the cap is kept.
    """
    result: dict = {"home_text": "", "index_text": "", "projects": []}
    try:
        await asyncio.wait_for(_crawl(url, browser, result), timeout=PORTFOLIO_TIMEOUT)
    except (asyncio.TimeoutError, Exception):
        pass
    return result

# ── Batch scraper (caller-owned browser) ─────────────────────────────────────

async def scrape_portfolios_batch(
    entries: list[dict],
    browser: Browser,
    concurrency: int = 3,
    progress_callback=None,
) -> dict[str, dict]:
    """
    Crawl multiple portfolios using the supplied *browser* instance.

    Args:
        entries:           list of dicts with at least a 'url' key
        browser:           Playwright Browser — owned by the caller
        concurrency:       max portfolios crawled at the same time
        progress_callback: optional async callable(entry, result)

    Returns:
        dict  url → crawl result (see scrape_portfolio)
    """
    results: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def _worker(entry: dict) -> None:
        async with semaphore:
            url = entry["url"]
            data = await scrape_portfolio(url, browser)
            results[url] = data
            if progress_callback:
                await progress_callback(entry, data)

    await asyncio.gather(*[_worker(e) for e in entries])
    return results

# ── Smoke-test (run directly) ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    TEST = [{"url": u} for u in sys.argv[1:]] or [
        {"url": "https://sawad.framer.website"},
        {"url": "https://aaftab.is-a.dev"},
        {"url": "https://aahana-surya.github.io"},
    ]

    async def _test():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            t0 = time.time()
            res = await scrape_portfolios_batch(TEST, browser, concurrency=3)
            await browser.close()
        for e in TEST:
            r = res[e["url"]]
            print(f"\n{'='*60}\n{e['url']} | home {len(r['home_text'])} chars | "
                  f"{len(r['projects'])} projects")
            for p in r["projects"]:
                print(f"  - {p['title']!r} -> {p['url']} "
                      f"(card {len(p['card_text'])}, detail {len(p['detail_text'])})")
        print(f"\n{time.time() - t0:.1f}s")

    asyncio.run(_test())
