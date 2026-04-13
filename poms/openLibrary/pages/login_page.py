"""
openLibrary/pages/login_page.py — Pure POM for the OpenLibrary login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No flow logic, no credentials, no retry loops.

The glue layer (sites/openlibrary/pages/login_action.py) wraps these
interactions into a named Stepper behavior. JSON workflows call the
behavior by name — they never see a selector.
"""

from __future__ import annotations
import logging

from poms.openLibrary.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class LoginPage(BasePage):
    # ── Selectors used for state-checks only (not interactive inputs) ──────────
    LOGGED_IN      = "a[href='/account']"
    PROTECTED_PATH = "/account/books/want-to-read"

    # ── Locators — cfg lists are the single source of truth for interactions ──
    USERNAME_CFG = [
        {"label":       "Username",  "priority": 10},
        {"placeholder": "Username",  "priority": 20},
        {"id":          "username",  "priority": 30},
        {"css":         "#username", "priority": 40},
    ]
    PASSWORD_CFG = [
        {"label":       "Password",  "priority": 10},
        {"placeholder": "Password",  "priority": 20},
        {"id":          "password",  "priority": 30},
        {"css":         "#password", "priority": 40},
    ]
    SUBMIT_CFG = [
        {"role": "button", "name": "Log in",  "priority": 10},
        {"role": "button", "name": "Sign in", "priority": 20},
        {"css":  ".cta-btn--primary",         "priority": 30},
    ]

    @property
    def url(self) -> str:
        return f"{self.base_url}/account/login"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector("#username", timeout=15_000)
        except Exception:
            pass  # page may already be past the form

    async def is_logged_in(self) -> bool:
        try:
            return await self._driver.locator_count(self.LOGGED_IN) > 0
        except Exception:
            return False

    async def is_session_live(self) -> bool:
        """
        Navigate to a protected page and check login state via redirect detection.

        Uses a 60s timeout — OpenLibrary authenticated pages are slow.
        Uses 'commit' strategy so we return as soon as the server responds,
        not after the full page load (which can hang on lazy analytics).
        """
        protected = f"{self.base_url.rstrip('/')}{self.PROTECTED_PATH}"
        try:
            await self._driver.goto(protected, wait_until="commit", timeout=60_000)
        except Exception:
            # Timeout or network error — treat as not logged in, let login proceed
            return False
        return await self.is_logged_in()

    async def fill_username(self, value: str) -> None:
        await self._resolve_and_fill_any(self.USERNAME_CFG, value, "username field")

    async def fill_password(self, value: str) -> None:
        await self._resolve_and_fill_any(self.PASSWORD_CFG, value, "password field")

    async def submit(self) -> None:
        await self._resolve_and_click_any(self.SUBMIT_CFG, "login submit button")
        await self._driver.wait_for_load_state("domcontentloaded")
