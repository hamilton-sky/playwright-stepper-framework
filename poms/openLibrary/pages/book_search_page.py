"""
pages/book_search_page.py — Pure POM for OpenLibrary search page.

Responsibility: orchestrate the search page flow.
  open → search → collect → paginate

Uses:
  - openlibrary_exam.utils.book_filter  (year extraction — pure functions)
  - openlibrary_exam.pages.base_page    (BasePage)
  - driver (PlaywrightDriver)           for all DOM interactions

No src/ imports. No framework imports.
"""
from __future__ import annotations
import asyncio
import logging
from urllib.parse import quote_plus

from poms.openLibrary.pages.base_page import BasePage
from poms.openLibrary.utils.book_filter import extract_year_from_text, is_under_year

logger = logging.getLogger(__name__)


class BookSearchPage(BasePage):
    """
    POM for the OpenLibrary search page.

    All CSS selectors live in the inner Locators class — single source of truth.
    Nothing outside this file should hardcode these strings (Option 3).
    """

    class Locators:
        """
        CSS selectors — verified against live OpenLibrary DOM (April 2026)
        via Playwright inspection (JS-rendered, not static HTML).

        Search results: <li class="searchResultItem sri--w-main" ...>
        Year text:      <span class="resultDetails"><span>First published in YYYY</span>...</span>
        Shelf button:   <button class="book-progress-btn primary-action unactivated">
        """
        # ── Result Item Selectors ─────────────────────────────────────────
        RESULT_ITEM = "li.searchResultItem"  # verified: 20 matches on Dune search

        RESULT_ITEM_CFGS: list[dict] = [
            {"css": "li.searchResultItem",            "priority": 10, "label": "searchResultItem"},
            {"css": "li:has(a[href*='/works/'])",     "priority": 20, "label": "works-link-li"},
            {"css": "ul.list-books li",               "priority": 30, "label": "list-books-li"},
            {"css": "#contentBody li",                "priority": 40, "label": "contentBody-li"},
        ]

        # ── Year/Date Selectors ─────────────────────────────────────────
        # span.resultDetails is the grandparent of the year text node.
        # inner_text() on that span returns "First published in YYYY — N editions".
        YEAR_TEXT_CFGS: list[dict] = [
            {"css": "span.resultDetails",            "priority": 10, "label": "resultDetails"},
            {"css": "span[class*='result']",         "priority": 20, "label": "result-span"},
            {"css": "[class*='published']",          "priority": 30, "label": "published-attr"},
        ]
        # If none of the above selectors match, _collect_from_page falls back to
        # reading the entire li inner_text() — "First published in YYYY" is always present.

        # ── Search Input Selectors ────────────────────────────────────────
        SEARCH_INPUT = "input#q"  # verified: OpenLibrary search input has id="q"
        SEARCH_INPUT_CFGS: list[dict] = [
            {"role": "searchbox",           "priority": 10},
            {"label": "Search",             "priority": 20},
            {"placeholder": "Search",       "priority": 30},
            {"id":  "q",                    "priority": 40},
            {"css": "input#q",              "priority": 50},
            {"css": "input[name='q']",      "priority": 60},
            {"css": "input[type='search']", "priority": 70},
        ]

        SEARCH_BUTTON = "button[type='submit']"
        SEARCH_BUTTON_CFGS: list[dict] = [
            {"role": "button", "name": "Search", "priority": 10},
            {"role": "button", "name": "Go",     "priority": 20},
            {"css": "button[type='submit']",     "priority": 30},
        ]

    def __init__(self, driver, base_url: str, delays=None,
                 page=None, resolver=None):
        super().__init__(driver, base_url, delays, page=page, resolver=resolver)
        self._query    = ""
        self._page_num = 1

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/search"

    async def open(self) -> None:
        pass  # search() owns the /search navigation — open() is intentionally a no-op

    async def wait_for_ready(self) -> None:
        pass

    async def search(self, query: str) -> None:
        """
        Navigate to search page without waiting for page load events.

        OpenLibrary's search hangs when waiting for domcontentloaded/load after
        the clearing phase. Instead, return immediately and use polling to check
        if results appear.
        """
        import time as _time
        self._query    = query
        self._page_num = 1

        search_url = f"{self.base_url.rstrip('/')}/search?q={quote_plus(query)}"
        logger.info("Navigating to search URL: %s", search_url)

        # Navigate WITHOUT waiting for page load events (they may hang)
        t0 = _time.monotonic()
        try:
            # Use commit strategy: return as soon as response is received, don't wait for page events
            await self._driver.goto(search_url, wait_until="commit", timeout=30_000)
            logger.info("Navigation sent (commit strategy) in %.0fms", (_time.monotonic() - t0) * 1000)
        except Exception as e:
            logger.warning("Navigation attempt failed: %s — proceeding with polling", str(e)[:80])

        # Poll for results to appear in DOM
        logger.info("Polling for search results to load…")
        max_wait = 20
        for attempt in range(max_wait):
            try:
                count = await self._driver.locator_count(self.Locators.RESULT_ITEM)
                if count > 0:
                    elapsed = (_time.monotonic() - t0) * 1000
                    logger.info("Search results loaded in %.0fms (after %d polling attempts)", elapsed, attempt + 1)
                    return
            except Exception:
                pass

            if attempt < max_wait - 1:
                await asyncio.sleep(0.5)

        logger.warning("Search results did not appear after polling — proceeding with collection attempt")





    async def collect_books_under_year(self, max_year: int, limit: int) -> list[str]:
        """
        Collect book URLs from search results, filtered by max publication year.
        Paginates automatically until limit is reached or pages run out.

        Page cap comes from delays.max_search_pages (config-driven, not hardcoded).
        """
        collected: list[str] = []
        max_pages = self.delays.max_search_pages  # from config, not magic number
        logger.info("Collecting up to %d books published before %d (max %d pages)",
                    limit, max_year, max_pages)

        while len(collected) < limit and self._page_num <= max_pages:
            remaining = limit - len(collected)
            logger.info("Scanning page %d — need %d more book(s)", self._page_num, remaining)
            page_results = await self._collect_from_page(max_year, remaining)
            collected.extend(page_results)
            logger.info("Page %d: found %d qualifying book(s) — total so far: %d/%d",
                        self._page_num, len(page_results), len(collected), limit)

            if len(collected) >= limit:
                break

            self._page_num += 1
            logger.info("Paginating to page %d…", self._page_num)
            await asyncio.sleep(self.delays.between_pagination_ms / 1000)

            next_url = (
                f"{self.base_url.rstrip('/')}/search"
                f"?q={self._query}&page={self._page_num}"
            )
            import time as _time
            _t = _time.monotonic()

            # Retry once on navigation timeout
            try:
                await self._driver.goto(next_url, wait_until="domcontentloaded", timeout=45_000)
                logger.info("Page %d loaded in %.0fms", self._page_num, (_time.monotonic() - _t) * 1000)
            except Exception as e:
                logger.warning("Page %d navigation failed (%s) — retrying once", self._page_num, str(e)[:80])
                try:
                    await asyncio.sleep(2)
                    await self._driver.goto(next_url, wait_until="domcontentloaded", timeout=45_000)
                    logger.info("Page %d loaded on retry in %.0fms", self._page_num, (_time.monotonic() - _t) * 1000)
                except Exception as e2:
                    logger.warning("Page %d navigation failed on retry — stopping pagination", self._page_num)
                    break

            await asyncio.sleep(self.delays.page_load_wait_ms / 1000)

            # Page is already loaded — use count() for instant check, no timeout wait
            result_found = False
            for cfg in self.Locators.RESULT_ITEM_CFGS:
                count = await self._driver.locator_count(cfg["css"])
                if count > 0:
                    logger.debug("Page %d results found via selector: %s (%d items)", self._page_num, cfg.get("label", cfg["css"]), count)
                    result_found = True
                    break

            if not result_found:
                logger.warning("No results on page %d — stopping pagination", self._page_num)
                break

        logger.info("Collection complete: %d/%d books collected", len(collected), limit)
        return collected

    async def _collect_from_page(self, max_year: int, limit: int) -> list[str]:
        """
        Collect qualifying book URLs from the current page.

        Strategy:
        1. Find result items using primary selector (or fallback if needed)
        2. For each item, try multiple year extraction selectors
        3. Extract href and build full URLs

        Uses Playwright Locator API — re-queries lazily, never produces stale handles.
        """
        urls: list[str] = []

        # Use primary selector first, fall back if needed
        items = self._driver.locator(self.Locators.RESULT_ITEM)
        count = await items.count()

        if count == 0:
            # Primary selector failed, try next option
            for cfg in self.Locators.RESULT_ITEM_CFGS[1:]:
                items = self._driver.locator(cfg["css"])
                count = await items.count()
                if count > 0:
                    logger.info("Page %d: using fallback selector %s", self._page_num, cfg.get("label", cfg["css"]))
                    break

        logger.info("Page %d: examining %d result item(s)", self._page_num, count)

        for i in range(count):
            if len(urls) >= limit:
                break

            item = items.nth(i)

            # Year extraction with resilience: try multiple selectors
            year_text = ""
            for cfg in self.Locators.YEAR_TEXT_CFGS:
                try:
                    year_loc = item.locator(cfg["css"])
                    if await year_loc.count() > 0:
                        year_text = await year_loc.first.inner_text()
                        if year_text:
                            logger.info("    Year text from %s: %r", cfg.get("label", cfg["css"]), year_text[:80])
                            break
                except Exception:
                    continue

            if not year_text:
                logger.info("  [%d/%d] no year text found — selectors tried: %s",
                            i + 1, count, [c.get("label", c["css"]) for c in self.Locators.YEAR_TEXT_CFGS])

            year = extract_year_from_text(year_text)
            if not is_under_year(year, max_year):
                logger.info("  [%d/%d] skipped — extracted year %s from %r (max=%d)",
                            i + 1, count, year, year_text[:40], max_year)
                continue

            try:
                href = await item.locator("a").first.get_attribute("href")
                if href:
                    full_url = self.base_url.rstrip("/") + href
                    urls.append(full_url)
                    logger.info("  [%d/%d] accepted — year %s — %s", i + 1, count, year, full_url)
            except Exception:
                continue

        return urls
