"""ti/pages/drag_and_drop_page.py — Pure POM for the-internet drag and drop page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class DragAndDropPage(BasePage):

    class Locators:
        COLUMN_A = Locator(
            id="column-a",
            css="#column-a",
            description="draggable column A",
        )
        COLUMN_B = Locator(
            id="column-b",
            css="#column-b",
            description="draggable column B",
        )

        # Read-only state check
        COLUMN_HEADERS = "#columns .column header"

    @property
    def url(self) -> str:
        return f"{self.base_url}/drag_and_drop"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.COLUMN_A.css or "#column-a", timeout=15_000
            )
        except Exception:
            pass

    async def drag_a_onto_b(self) -> None:
        if self._page:
            await self._page.drag_and_drop(
                self.Locators.COLUMN_A.css or "#column-a",
                self.Locators.COLUMN_B.css or "#column-b",
            )

    async def get_column_order(self) -> list[str]:
        handles = await self._driver.query_selector_all(self.Locators.COLUMN_HEADERS)
        return [await h.inner_text() for h in handles]
