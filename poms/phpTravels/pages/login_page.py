"""
phpTravels/pages/login_page.py — Pure POM for the phpTravels login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No credentials, no flow logic, no retry loops.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    class Locators:
        # ── Read-only state checks ────────────────────────────────────────────
        USER_DROPDOWN = ".dropdown-toggle img.rounded-circle"
        ERROR_ALERT   = ".alert-danger"

        # ── Interactive ───────────────────────────────────────────────────────
        EMAIL = Locator(
            label="Email",
            placeholder="Email",
            css="input[name='username']",
            description="email login field",
        )
        PASSWORD = Locator(
            label="Password",
            placeholder="Password",
            css="input[name='password']",
            description="password field",
        )
        SUBMIT = Locator(
            role="button", name="Login",
            css="button[type='submit']",
            description="login submit button",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/account/login"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.EMAIL.css, timeout=15_000
            )
        except Exception:
            pass

    async def fill_email(self, value: str) -> None:
        await self._interact(self.Locators.EMAIL, "fill", value=value)

    async def fill_password(self, value: str) -> None:
        await self._interact(self.Locators.PASSWORD, "fill", value=value)

    async def submit(self) -> None:
        await self._interact(self.Locators.SUBMIT, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        return await self._get_text_or_none(self.Locators.ERROR_ALERT)

    async def is_logged_in(self) -> bool:
        try:
            return await self._driver.locator_count(self.Locators.USER_DROPDOWN) > 0
        except Exception:
            return False
