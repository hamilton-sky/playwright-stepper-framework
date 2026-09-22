"""ti/pages/secure_page.py — Pure POM for the-internet secure area page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class SecurePage(BasePage):

    class Locators:
        LOGOUT = Locator(
            role="link", name="Logout",
            css="a[href='/logout']",
            description="logout link",
        )

        # Read-only state checks
        SECURE_HEADING = "h2"
        SUCCESS_FLASH  = ".flash.success"

    @property
    def url(self) -> str:
        return f"{self.base_url}/secure"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.LOGOUT.css, timeout=15_000
            )
        except Exception:
            pass

    async def click_logout(self) -> None:
        await self._interact(self.Locators.LOGOUT, "click")

    async def is_secure(self) -> bool:
        count = await self._driver.locator_count(self.Locators.SECURE_HEADING)
        return count > 0

    async def get_flash_message(self) -> str | None:
        el = await self._driver.query_selector(self.Locators.SUCCESS_FLASH)
        if el:
            return (await el.inner_text()).strip()
        return None
