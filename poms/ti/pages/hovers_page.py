"""ti/pages/hovers_page.py — Pure POM for the-internet hovers page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class HoversPage(BasePage):

    class Locators:
        USER_AVATAR_1 = Locator(
            role="img", name="User Avatar",
            css=".figure:nth-child(1) img",
            description="first user avatar image (hover to reveal profile link)",
        )
        VIEW_PROFILE_1 = Locator(
            role="link", name="View profile",
            css="a[href='/users/1']",
            description="view profile link for user 1 (visible after hover)",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/hovers"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.USER_AVATAR_1.css, timeout=15_000
            )
        except Exception:
            pass

    async def hover_user_avatar_1(self) -> None:
        el = await self._driver.query_selector(self.Locators.USER_AVATAR_1.css)
        if el:
            await el.hover()

    async def click_view_profile_1(self) -> None:
        await self._interact(self.Locators.VIEW_PROFILE_1, "click")
