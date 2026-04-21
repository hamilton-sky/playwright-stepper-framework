"""
pages/book_search_page.py — Pure POM for OpenLibrary search page.

Responsibility: orchestrate the search page flow.
  open → search → collect → paginate
"""
from __future__ import annotations
import asyncio
import logging
from urllib.parse import quote_plus

from poms.openLibrary.pages.base_page import BasePage
from poms.openLibrary.utils.book_filter import extract_year_from_text, is_under_year
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class BookSearchPage(BasePage):

    class Locators:
        # ── Read-only — one element, multiple CSS fallbacks ───────────────────
        RESULT_ITEM = Locator(
            css="li.searchResultItem",
            css_fallbacks=[
                "li:has(a[href*='/works/'])",
                "ul.list-books li",
                "#contentBody li",
            ],
            description="search result item",
        )
        YEAR_TEXT = Locator(
            css="span.resultDetails",
            css_fallbacks=[
                "span[class*='result']",
                "[class*='published']",
            ],
            description="publication year text",
        )

        # ── Interactive (reserved for form-based search) ──────────────────────
        SEARCH_INPUT = Locator(
            placeholder="Search",
            css="input[name='q']",
            description="search input field",
        )
        SEARCH_BUTTON = Locator(
            css="input.search-bar-submit",
            css_fallbacks=["input[type='submit']"],
            description="search submit button",
        )

    def __init__(self, driver, base_url: str, delays=None,
                 page=None, resolver=None, **kwargs):
        super().__init__(driver, base_url, delays, page=page, resolver=resolver, **kwargs)
        self._query    = ""
        self._page_num = 1

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/search"

    async def open(self) -> None:
        pass  # search() owns navigation

    async def wait_for_ready(self) -> None:
        pass

    async def search(self, query: str) -> None:
        import time as _time
        self._query    = query
        self._page_num = 1

        search_url = f"{self.base_url.rstrip('/')}/search?q={quote_plus(query)}"
        logger.info("Navigating to search URL: %s", search_url)

        t0 = _time.monotonic()
        try:
            await self._driver.goto(search_url, wait_until="commit", timeout=30_000)
            logger.info("Navigation sent (commit strategy) in %.0fms", (_time.monotonic() - t0) * 1000)
        except Exception as e:
            logger.warning("Navigation attempt failed: %s — proceeding with polling", str(e)[:80])

        logger.info("Polling for search results to load…")
        max_wait = 20
        for attempt in range(max_wait):
            try:
                count = await self._driver.locator_count(self.Locators.RESULT_ITEM.css)
                if count > 0:
                    elapsed = (_time.monotonic() - t0) * 1000
                    logger.info("Search results loaded in %.0fms (after %d polling attempts)", elapsed, attempt + 1)
                    return
            except Exception:
                pass
            if attempt < max_wait - 1:
                await asyncio.sleep(0.5)

        logger.warning("Search results did not appear after polling — proceeding with collection attempt")

    async def collect_books_under_year(self, max_year: int, limit: int) -> list[dict]:
        collected: list[dict] = []
        seen_urls: set[str] = set()
        max_pages = self.delays.max_search_pages
        logger.info("Collecting up to %d books published before %d (max %d pages)",
                    limit, max_year, max_pages)

        while len(collected) < limit and self._page_num <= max_pages:
            remaining = limit - len(collected)
            logger.info("Scanning page %d — need %d more book(s)", self._page_num, remaining)
            page_results = await self._collect_from_page(max_year, remaining)
            for item in page_results:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    collected.append(item)
            logger.info("Page %d: found %d qualifying book(s) — total so far: %d/%d",
                        self._page_num, len(page_results), len(collected), limit)

            if len(collected) >= limit:
                break

            self._page_num += 1
            logger.info("Paginating to page %d…", self._page_num)
            await self._sleep(self.delays.between_pagination_ms)

            next_url = (
                f"{self.base_url.rstrip('/')}/search"
                f"?q={self._query}&page={self._page_num}"
            )
            import time as _time
            _t = _time.monotonic()

            try:
                await self._driver.goto(next_url, wait_until="domcontentloaded", timeout=45_000)
                logger.info("Page %d loaded in %.0fms", self._page_num, (_time.monotonic() - _t) * 1000)
            except Exception as e:
                logger.warning("Page %d navigation failed (%s) — retrying once", self._page_num, str(e)[:80])
                try:
                    await asyncio.sleep(2)
                    await self._driver.goto(next_url, wait_until="domcontentloaded", timeout=45_000)
                    logger.info("Page %d loaded on retry in %.0fms", self._page_num, (_time.monotonic() - _t) * 1000)
                except Exception:
                    logger.warning("Page %d navigation failed on retry — stopping pagination", self._page_num)
                    break

            await self._sleep(self.delays.page_load_wait_ms)

            # Try primary then fallbacks until results found
            result_found = False
            for css in self.Locators.RESULT_ITEM.css_candidates():
                if await self._driver.locator_count(css) > 0:
                    logger.debug("Page %d results found via: %s", self._page_num, css)
                    result_found = True
                    break

            if not result_found:
                logger.warning("No results on page %d — stopping pagination", self._page_num)
                break

        logger.info("Collection complete: %d/%d books collected", len(collected), limit)
        return collected

    async def _collect_from_page(self, max_year: int, limit: int) -> list[dict]:
        urls: list[dict] = []

        # Try primary CSS first, then fallbacks
        items = self._driver.locator(self.Locators.RESULT_ITEM.css)
        count = await items.count()

        if count == 0:
            for css in self.Locators.RESULT_ITEM.css_fallbacks:
                items = self._driver.locator(css)
                count = await items.count()
                if count > 0:
                    logger.info("Page %d: using fallback selector: %s", self._page_num, css)
                    break

        logger.info("Page %d: examining %d result item(s)", self._page_num, count)

        for i in range(count):
            if len(urls) >= limit:
                break

            item = items.nth(i)

            # Try primary year-text CSS then fallbacks
            year_text = ""
            for css in self.Locators.YEAR_TEXT.css_candidates():
                try:
                    year_loc = item.locator(css)
                    if await year_loc.count() > 0:
                        year_text = await year_loc.first.inner_text()
                        if year_text:
                            logger.info("    Year text from %s: %r", css, year_text[:80])
                            break
                except Exception:
                    continue

            if not year_text:
                logger.info("  [%d/%d] no year text found — selectors tried: %s",
                            i + 1, count, self.Locators.YEAR_TEXT.css_candidates())

            year = extract_year_from_text(year_text)
            if not is_under_year(year, max_year):
                logger.info("  [%d/%d] skipped — extracted year %s from %r (max=%d)",
                            i + 1, count, year, year_text[:40], max_year)
                continue

            try:
                href = await item.locator("a").first.get_attribute("href")
                if href:
                    full_url = self.base_url.rstrip("/") + href
                    year_int = year[0] if isinstance(year, list) and year else year
                    urls.append({"url": full_url, "year": year_int})
                    logger.info("  [%d/%d] accepted — year %s — %s", i + 1, count, year_int, full_url)
            except Exception:
                continue

        return urls
