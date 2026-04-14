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
    # "My Books" nav link — only present when authenticated (verified via page snapshot)
    LOGGED_IN      = "a[href*='/account/books']"
    PROTECTED_PATH = "/account/books/want-to-read"

    # ── Locators — cfg lists are the single source of truth for interactions ──
    # OL login form uses "Email" label (not "Username") — confirmed via page snapshot
    USERNAME_CFG = [
        {"label":       "Email",     "priority": 10},
        {"placeholder": "Email",     "priority": 20},
        {"id":          "username",  "priority": 30},
        {"css":         "#username", "priority": 40},
    ]
    PASSWORD_CFG = [
        {"label":       "Password",  "priority": 10},
        {"placeholder": "Password",  "priority": 20},
        {"id":          "password",  "priority": 30},
        {"css":         "#password", "priority": 40},
    ]
    # Button text is "Log In" (capital I) — confirmed via page snapshot
    SUBMIT_CFG = [
        {"role": "button", "name": "Log In",     "priority": 10},
        {"css":  ".cta-btn--primary",            "priority": 20},
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
        """
        URL-based check — consistent with is_session_live().
        After a successful login OL never stays on /account/login.
        Falls back to DOM check if URL is ambiguous.
        """
        try:
            if "/account/login" not in self._driver.current_url:
                return True
            return await self._driver.locator_count(self.LOGGED_IN) > 0
        except Exception:
            return False

    async def is_session_live(self) -> bool:
        """
        Navigate to a protected page and check login state via URL after redirect.

        Uses domcontentloaded so the final URL is settled before we read it.
        URL check is instantaneous and has no DOM-render race condition —
        OpenLibrary redirects unauthenticated requests to /account/login.
        """
        protected = f"{self.base_url.rstrip('/')}{self.PROTECTED_PATH}"
        try:
            await self._driver.goto(protected, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            # Timeout or network error — treat as not logged in, let login proceed
            return False
        return "/account/login" not in self._driver.current_url

    async def fill_username(self, value: str) -> None:
        await self._resolve_and_fill_any(self.USERNAME_CFG, value, "username field")

    async def fill_password(self, value: str) -> None:
        await self._resolve_and_fill_any(self.PASSWORD_CFG, value, "password field")

    async def submit(self) -> None:
        import asyncio
        # js_click fires immediately; wait_for_load_state may return before the
        # form-submit redirect completes (login page is already in domcontentloaded).
        # Poll until the URL leaves /account/login (up to 10s) to guarantee the
        # redirect has settled before is_logged_in() checks the URL.
        await self._resolve_and_click_any(self.SUBMIT_CFG, "login submit button", js_click=True)
        await self._driver.wait_for_load_state("domcontentloaded")
        for _ in range(20):
            if "/account/login" not in self._driver.current_url:
                break
            await asyncio.sleep(0.5)
