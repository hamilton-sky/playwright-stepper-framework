"""
pages/reading_list_page.py — Pure POM for OpenLibrary reading list.

Responsibility: navigate to reading list pages and count books.
"""
from __future__ import annotations
import asyncio
import logging
from urllib.parse import urlparse

from poms.openLibrary.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class ReadingListPage(BasePage):

    _WANT_TO_READ_PATH = "/account/books/want-to-read"
    _ALREADY_READ_PATH = "/account/books/already-read"

    class Locators:
        # All selectors are read-only / existence checks — no resolver needed.
        BOOK_ITEM = "ul.list-books > li"
        BOOK_HREF = "a[href*='/works/'], a[href*='/books/']"
        NEXT_PAGE = Locator(
            css="a.ChoosePage[data-ol-link-track='Pager|Next']",
            description="pagination next page link",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self._WANT_TO_READ_PATH}"

    async def get_book_count(self) -> int:
        """Count books across both shelves (want-to-read + already-read)."""
        want    = await self._count_shelf(self._WANT_TO_READ_PATH)
        already = await self._count_shelf(self._ALREADY_READ_PATH)
        logger.debug(f"Count: {want} want-to-read + {already} already-read = {want + already}")
        return want + already

    async def collect_all_book_urls(self, shelf_path: str) -> list[str]:
        """Collect all book URLs from a shelf, paginating until done."""
        base = self.base_url.rstrip("/")
        await self._driver.goto(f"{base}{shelf_path}", wait_until="domcontentloaded")
        book_urls: list[str] = []

        while True:
            items = await self._driver.query_selector_all(self.Locators.BOOK_ITEM)
            for item in items:
                link = await item.query_selector(self.Locators.BOOK_HREF)
                if not link:
                    continue
                href = await link.get_attribute("href")
                if href:
                    clean = urlparse(base + href)._replace(query="", fragment="").geturl()
                    book_urls.append(clean)

            if not await self._click_next_page_if_present():
                break
            await self._driver.wait_for_load_state("domcontentloaded")
            await self._sleep(self.delays.between_pagination_ms)

        return book_urls

    async def _count_shelf(self, path: str) -> int:
        await self._driver.goto(
            f"{self.base_url.rstrip('/')}{path}",
            wait_until="domcontentloaded",
        )
        total = 0
        while True:
            items = await self._driver.query_selector_all(self.Locators.BOOK_ITEM)
            total += len(items)

            if not await self._click_next_page_if_present():
                break
            await self._driver.wait_for_load_state("domcontentloaded")
            await self._sleep(self.delays.between_pagination_ms)

        return total

    async def _click_next_page_if_present(self) -> bool:
        """Return False quietly when the shelf has no next page."""
        css = self.Locators.NEXT_PAGE.css
        if css:
            try:
                if await self._driver.locator_count(css) == 0:
                    return False
            except Exception:
                pass
        return await self._interact(self.Locators.NEXT_PAGE, "click")
