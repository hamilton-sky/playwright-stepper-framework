"""
phpTravels/pages/login_page.py — Pure POM for the phpTravels login page.

Single responsibility: owns every selector for the login form and exposes
raw page interactions. No credentials, no flow logic, no retry loops.

The glue layer (stepper/sites/phptravels/pages/login_action.py) wraps these
into a named Stepper behavior.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class LoginPage(BasePage):

    class Locators:
        """All login-page selectors. Never duplicated elsewhere."""
        EMAIL         = "input[name='username']"
        PASSWORD      = "input[name='password']"
        SUBMIT        = "button[type='submit']"
        # Present on any authenticated page — confirms successful login
        USER_DROPDOWN = ".dropdown-toggle img.rounded-circle"
        ERROR_ALERT   = ".alert-danger"

    @property
    def url(self) -> str:
        return f"{self.base_url}/account/login"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.EMAIL, timeout=15_000
            )
        except Exception:
            pass

    # ── Raw interactions ───────────────────────────────────────────────────────

    async def fill_email(self, value: str) -> None:
        await self._driver.fill(self.Locators.EMAIL, value)

    async def fill_password(self, value: str) -> None:
        await self._driver.fill(self.Locators.PASSWORD, value)

    async def submit(self) -> None:
        await self._driver.click(self.Locators.SUBMIT)
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        """Return the error alert text, or None if no error is visible."""
        try:
            el = await self._driver.query_selector(self.Locators.ERROR_ALERT)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return None

    async def is_logged_in(self) -> bool:
        """True if the user avatar/dropdown is present in the nav bar."""
        try:
            return await self._driver.locator_count(self.Locators.USER_DROPDOWN) > 0
        except Exception:
            return False
