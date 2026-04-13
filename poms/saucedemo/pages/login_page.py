"""
saucedemo/pages/login_page.py — Pure POM for the SauceDemo login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No credentials, no flow logic, no retry loops.

The glue layer (stepper/sites/saucedemo/pages/login_action.py) wraps these
into a named Stepper behavior.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    class Locators:
        """All login-page selectors. Never duplicated elsewhere."""
        # ── Interactive inputs — cfg lists are the single source of truth ──────
        USERNAME_CFG = [
            {"css": "[data-test='username']",     "priority": 10},
            {"css": "#user-name",                 "priority": 20},
        ]
        PASSWORD_CFG = [
            {"css": "[data-test='password']",     "priority": 10},
            {"css": "#password",                  "priority": 20},
        ]
        SUBMIT_CFG = [
            {"css": "[data-test='login-button']", "priority": 10},
            {"role": "button", "name": "Login",   "priority": 20},
        ]
        # ── State-check selectors (read-only, not interactive inputs) ──────────
        ERROR_MSG = "[data-test='error']"
        APP_LOGO  = ".app_logo"  # present on any post-login page

    @property
    def url(self) -> str:
        return f"{self.base_url}/"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.USERNAME_CFG[0]["css"], timeout=15_000
            )
        except Exception:
            pass  # may already be past the form

    # ── Raw interactions ───────────────────────────────────────────────────────

    async def fill_username(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.USERNAME_CFG, value, "username field")

    async def fill_password(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.PASSWORD_CFG, value, "password field")

    async def submit(self) -> None:
        await self._resolve_and_click_any(self.Locators.SUBMIT_CFG, "login submit button")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        """Return the error banner text, or None if no error is visible."""
        try:
            el = await self._driver.query_selector(self.Locators.ERROR_MSG)
            if el:
                return await el.inner_text()
        except Exception:
            pass
        return None

    async def is_logged_in(self) -> bool:
        """True if the post-login app logo is present (not on the login page)."""
        try:
            return await self._driver.locator_count(self.Locators.APP_LOGO) > 0
        except Exception:
            return False
