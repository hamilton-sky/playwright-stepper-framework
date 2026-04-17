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
        # Plain strings — used only for wait_for_selector / state reads
        EMAIL         = "input[name='username']"
        PASSWORD      = "input[name='password']"
        SUBMIT        = "button[type='submit']"
        USER_DROPDOWN = ".dropdown-toggle img.rounded-circle"
        ERROR_ALERT   = ".alert-danger"

        # Interactive cfg lists — used by fill/click helpers
        EMAIL_CFG = [
            {"label":       "Email",                 "priority": 10},
            {"placeholder": "Email",                 "priority": 20},
            {"css":         "input[name='username']","priority": 30},
        ]
        PASSWORD_CFG = [
            {"label":       "Password",              "priority": 10},
            {"placeholder": "Password",              "priority": 20},
            {"css":         "input[name='password']","priority": 30},
        ]
        SUBMIT_CFG = [
            {"role": "button", "name": "Login",      "priority": 10},
            {"role": "button", "name": "Sign In",    "priority": 20},
            {"css":  "button[type='submit']",        "priority": 30},
        ]

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
        await self._resolve_and_fill_any(self.Locators.EMAIL_CFG, value)

    async def fill_password(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.PASSWORD_CFG, value)

    async def submit(self) -> None:
        await self._resolve_and_click_any(self.Locators.SUBMIT_CFG)
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        """Return the error alert text, or None if no error is visible."""
        return await self._get_text_or_none(self.Locators.ERROR_ALERT)

    async def is_logged_in(self) -> bool:
        """True if the user avatar/dropdown is present in the nav bar."""
        try:
            return await self._driver.locator_count(self.Locators.USER_DROPDOWN) > 0
        except Exception:
            return False
