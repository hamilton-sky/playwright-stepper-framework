from __future__ import annotations
import logging

from goodreads.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class GoodreadsSearchPage(BasePage):
    SEARCH_INPUT = "input#search_query_main"
    RESULT_ITEM = "tr.bookalike"

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(self.SEARCH_INPUT, timeout=10_000)
        except Exception:
            logger.warning("Search input not found - continuing")

    async def search(self, query: str) -> None:
        logger.info(f"Searching for: {query}")
        await self._driver.fill(self.SEARCH_INPUT, query)
        await self._driver.press(self.SEARCH_INPUT, "Enter")

    async def collect_items(self, limit: int) -> list[str]:
        raise NotImplementedError("Implement Goodreads result collection")
