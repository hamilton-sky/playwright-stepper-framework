"""ti/pages/login_page.py — Pure POM for the-internet login page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    class Locators:
        USERNAME = Locator(
            role="textbox", name="Username",
            label="Username",
            description="username input field",
        )
        PASSWORD = Locator(
            role="textbox", name="Password",
            label="Password",
            description="password input field",
        )
        LOGIN = Locator(
            role="button", name="Login",
            description="login submit button",
        )

        # Read-only state checks
        SUCCESS_FLASH = ".flash.success"
        ERROR_FLASH   = ".flash.error"

    @property
    def url(self) -> str:
        return f"{self.base_url}/login"

    async def wait_for_ready(self) -> None:
        # trace provided no css/id — wait on the login form element
        try:
            await self._driver.wait_for_selector("form", timeout=15_000)
        except Exception:
            pass

    async def fill_username(self, value: str) -> None:
        await self._interact(self.Locators.USERNAME, "fill", value=value)

    async def fill_password(self, value: str) -> None:
        await self._interact(self.Locators.PASSWORD, "fill", value=value)

    async def click_login(self) -> None:
        await self._interact(self.Locators.LOGIN, "click")

    async def open(self) -> None:
        await self._driver.goto(self.url)
        await self.wait_for_ready()

    async def is_logged_in(self) -> bool:
        count = await self._driver.locator_count(self.Locators.SUCCESS_FLASH)
        return count > 0

    async def get_error_message(self) -> str | None:
        el = await self._driver.query_selector(self.Locators.ERROR_FLASH)
        if el:
            return (await el.inner_text()).strip()
        return None
