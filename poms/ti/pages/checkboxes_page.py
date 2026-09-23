"""ti/pages/checkboxes_page.py — Pure POM for the-internet checkboxes page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class CheckboxesPage(BasePage):

    class Locators:
        # The generator wrote these as role+name only — `checkbox 1` and
        # `checkbox 2` — from the text it saw beside each input. That text is a
        # sibling node rather than a <label>, so the inputs have no accessible
        # name and get_by_role(..., name=...) matches nothing. Verified against
        # markup copied from the live page: 0 matches by name, 2 by bare role.
        #
        # So css is the primary here rather than the fallback pom-layer.md
        # normally prefers: there is no semantic identifier to prefer.
        CHECKBOX_1 = Locator(
            css="#checkboxes input[type='checkbox']:nth-of-type(1)",
            description="first checkbox (initially unchecked)",
        )
        CHECKBOX_2 = Locator(
            css="#checkboxes input[type='checkbox']:nth-of-type(2)",
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

    async def click_checkbox_1(self) -> bool:
        return await self._interact(self.Locators.CHECKBOX_1, "click")

    async def click_checkbox_2(self) -> bool:
        return await self._interact(self.Locators.CHECKBOX_2, "click")
