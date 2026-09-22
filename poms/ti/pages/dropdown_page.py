"""ti/pages/dropdown_page.py — Pure POM for the-internet dropdown page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class DropdownPage(BasePage):

    class Locators:
        DROPDOWN = Locator(
            role="combobox", name="Dropdown List",
            id="dropdown",
            css="#dropdown",
            description="dropdown list selector",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/dropdown"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.DROPDOWN.css, timeout=15_000
            )
        except Exception:
            pass

    async def select_dropdown(self, value: str) -> None:
        await self._select_option(self.Locators.DROPDOWN.css or "#dropdown", value)
