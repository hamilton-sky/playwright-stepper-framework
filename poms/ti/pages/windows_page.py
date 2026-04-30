"""ti/pages/windows_page.py — Pure POM for the-internet windows page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class WindowsPage(BasePage):

    class Locators:
        CLICK_HERE = Locator(
            role="link", name="Click Here",
            css="a[href='/windows/new']",
            description="link that opens a new browser window",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/windows"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.CLICK_HERE.css, timeout=15_000
            )
        except Exception:
            pass

    async def click_click_here(self) -> None:
        await self._interact(self.Locators.CLICK_HERE, "click")
