from __future__ import annotations
import logging

from goodreads.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class GoodreadsDetailPage(BasePage):
    ADD_BTN = "button.wantToRead"

    def __init__(self, driver, base_url: str, book_url: str, delays=None, page=None, resolver=None):
        super().__init__(driver, base_url, delays, page=page, resolver=resolver)
        self._book_url = book_url

    @property
    def url(self) -> str:
        return self._book_url

    async def add_to_shelf(self) -> bool:
        raise NotImplementedError("Implement Goodreads add-to-shelf")
