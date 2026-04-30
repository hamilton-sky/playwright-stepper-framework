"""ti/pages/checkboxes_page.py — Pure POM for the-internet checkboxes page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class CheckboxesPage(BasePage):

    class Locators:
        CHECKBOX_1 = Locator(
            role="checkbox", name="checkbox 1",
            description="first checkbox (initially unchecked)",
        )
        CHECKBOX_2 = Locator(
            role="checkbox", name="checkbox 2",
            description="second checkbox (initially checked)",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/checkboxes"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector("form", timeout=15_000)
        except Exception:
            pass

    async def click_checkbox_1(self) -> None:
        await self._interact(self.Locators.CHECKBOX_1, "click")

    async def click_checkbox_2(self) -> None:
        await self._interact(self.Locators.CHECKBOX_2, "click")
