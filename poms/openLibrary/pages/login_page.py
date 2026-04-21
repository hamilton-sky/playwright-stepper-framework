"""
openLibrary/pages/login_page.py — Pure POM for the OpenLibrary login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No flow logic, no credentials, no retry loops.
"""
from __future__ import annotations
import logging

from poms.openLibrary.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    # ── State-check selectors (read-only, no _interact needed) ───────────────
    LOGGED_IN      = "a[href*='/account/books']"
    PROTECTED_PATH = "/account/books/want-to-read"

    class Locators:
        USERNAME = Locator(
            label="Email",
            placeholder="Email",
            id="username",
            css="#username",
            description="email/username login field",
        )
        PASSWORD = Locator(
            label="Password",
            placeholder="Password",
            id="password",
            css="#password",
            description="password field",
        )
        SUBMIT = Locator(
            role="button", name="Log In",
            css=".cta-btn--primary",
            description="login submit button",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/account/login"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector("#username", timeout=15_000)
        except Exception:
            pass

    async def is_logged_in(self) -> bool:
        try:
            if "/account/login" not in self._driver.current_url:
                return True
            return await self._driver.locator_count(self.LOGGED_IN) > 0
        except Exception:
            return False

    async def is_session_live(self) -> bool:
        protected = f"{self.base_url.rstrip('/')}{self.PROTECTED_PATH}"
        try:
            await self._driver.goto(protected, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            return False
        return "/account/login" not in self._driver.current_url

    async def fill_username(self, value: str) -> None:
        await self._interact(self.Locators.USERNAME, "fill", value=value)

    async def fill_password(self, value: str) -> None:
        await self._interact(self.Locators.PASSWORD, "fill", value=value)

    async def submit(self) -> None:
        import asyncio
        await self._interact(self.Locators.SUBMIT, "click", js_click=True)
        await self._driver.wait_for_load_state("domcontentloaded")
        for _ in range(20):
            if "/account/login" not in self._driver.current_url:
                break
            await asyncio.sleep(0.5)
