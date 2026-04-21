"""
saucedemo/pages/login_page.py — Pure POM for the SauceDemo login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No credentials, no flow logic, no retry loops.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    class Locators:
        # ── Interactive ───────────────────────────────────────────────────────
        USERNAME = Locator(
            css="[data-test='username']",
            css_fallbacks=["#user-name"],
            description="username input field",
        )
        PASSWORD = Locator(
            css="[data-test='password']",
            css_fallbacks=["#password"],
            description="password input field",
        )
        SUBMIT = Locator(
            role="button", name="Login",
            css="[data-test='login-button']",
            description="login submit button",
        )

        # ── Read-only state checks ────────────────────────────────────────────
        ERROR_MSG = "[data-test='error']"
        APP_LOGO  = ".app_logo"

    @property
    def url(self) -> str:
        return f"{self.base_url}/"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.USERNAME.css, timeout=15_000
            )
        except Exception:
            pass

    async def fill_username(self, value: str) -> None:
        await self._interact(self.Locators.USERNAME, "fill", value=value)

    async def fill_password(self, value: str) -> None:
        await self._interact(self.Locators.PASSWORD, "fill", value=value)

    async def submit(self) -> None:
        await self._interact(self.Locators.SUBMIT, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        return await self._get_text_or_none(self.Locators.ERROR_MSG)

    async def is_logged_in(self) -> bool:
        try:
            return await self._driver.locator_count(self.Locators.APP_LOGO) > 0
        except Exception:
            return False
