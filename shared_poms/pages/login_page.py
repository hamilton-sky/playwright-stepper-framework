"""
shared_poms/pages/login_page.py — Pure POM for the OpenLibrary login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No flow logic, no credentials, no retry loops.

The glue layer (sites/openlibrary/pages/login_action.py) wraps these
interactions into a named Stepper behavior. JSON workflows call the
behavior by name — they never see a selector.
"""

from __future__ import annotations
import logging

from shared_poms.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class LoginPage(BasePage):
    # ── Selectors — the ONLY place in the codebase that knows login form CSS ──
    USERNAME  = "#username"
    PASSWORD  = "#password"
    SUBMIT    = ".cta-btn--primary"
    LOGGED_IN = "a[href='/account']"

    @property
    def url(self) -> str:
        return f"{self.base_url}/account/login"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(self.USERNAME, timeout=15_000)
        except Exception:
            pass  # page may already be past the form

    async def is_logged_in(self) -> bool:
        try:
            return await self._driver.locator_count(self.LOGGED_IN) > 0
        except Exception:
            return False

    async def fill_username(self, value: str) -> None:
        await self._driver.fill(self.USERNAME, value)

    async def fill_password(self, value: str) -> None:
        await self._driver.fill(self.PASSWORD, value)

    async def submit(self) -> None:
        await self._driver.click(self.SUBMIT)
        await self._driver.wait_for_load_state("domcontentloaded")
