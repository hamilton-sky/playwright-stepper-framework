"""
pages/reading_list_page.py — Pure POM for OpenLibrary reading list.

Responsibility: navigate to reading list pages and count books.

No src/ imports. No framework imports.
"""
from __future__ import annotations
import asyncio
import logging
from urllib.parse import urlparse

from shared_poms.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class ReadingListPage(BasePage):
    _WANT_TO_READ_PATH = "/account/books/want-to-read"
    _ALREADY_READ_PATH = "/account/books/already-read"
    _NEXT_PAGE         = "a.next-page, a[rel='next']"
    BOOK_ITEM_SELECTOR = "ul.list-books > li"
    _BOOK_HREF         = "a[href*='/works/'], a[href*='/books/']"

    def __init__(self, driver, base_url: str, delays=None,
                 page=None, resolver=None):
        super().__init__(driver, base_url, delays, page, resolver)

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
        """
        Collect all book URLs from a shelf, paginating until done.
        Ownership of pagination selectors lives here — not in FlowOrchestrator.
        """
        base = self.base_url.rstrip("/")
        await self._driver.goto(f"{base}{shelf_path}", wait_until="domcontentloaded")
        book_urls: list[str] = []

        while True:
            items = await self._driver.query_selector_all(self.BOOK_ITEM_SELECTOR)
            for item in items:
                link = await item.query_selector(self._BOOK_HREF)
                if not link:
                    continue
                href = await link.get_attribute("href")
                if href:
                    clean = urlparse(base + href)._replace(query="", fragment="").geturl()
                    book_urls.append(clean)

            clicked = await self._resolve_and_click(
                {"css": self._NEXT_PAGE},
                description="reading list next page",
            )
            if not clicked:
                break
            await self._driver.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(self.delays.between_pagination_ms / 1000)

        return book_urls

    async def _count_shelf(self, path: str) -> int:
        await self._driver.goto(
            f"{self.base_url.rstrip('/')}{path}",
            wait_until="domcontentloaded",
        )
        total = 0
        while True:
            items    = await self._driver.query_selector_all(self.BOOK_ITEM_SELECTOR)
            total   += len(items)
            clicked = await self._resolve_and_click(
                {"css": self._NEXT_PAGE},
                description="reading list next page",
            )
            if not clicked:
                break
            await self._driver.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(self.delays.between_pagination_ms / 1000)
        return total
