"""
saucedemo/pages/checkout_info_page.py — Pure POM for checkout step one.

Single responsibility: shipping-info form selectors and raw interactions.

Checkout step 1 of 2: customer fills first name, last name, and zip code.

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class CheckoutInfoPage(BasePage):

    class Locators:
        """All checkout-step-one selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        TITLE     = ".title"
        ERROR_MSG = "[data-test='error']"

        # ── Interactive inputs — cfg lists are the single source of truth ────
        FIRST_NAME_CFG = [
            {"css": "[data-test='firstName']", "priority": 10},
            {"placeholder": "First Name",      "priority": 20},
        ]
        LAST_NAME_CFG = [
            {"css": "[data-test='lastName']",  "priority": 10},
            {"placeholder": "Last Name",       "priority": 20},
        ]
        ZIP_CODE_CFG = [
            {"css": "[data-test='postalCode']", "priority": 10},
            {"placeholder": "Zip/Postal Code", "priority": 20},
        ]
        CONTINUE_CFG = [
            {"css":  "[data-test='continue']",   "priority": 10},
            {"role": "button", "name": "Continue", "priority": 20},
        ]
        CANCEL_CFG = [
            {"css":  "[data-test='cancel']",   "priority": 10},
            {"role": "button", "name": "Cancel", "priority": 20},
        ]

    @property
    def url(self) -> str:
        return f"{self.base_url}/checkout-step-one.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.FIRST_NAME_CFG[0]["css"], timeout=15_000
            )
        except Exception:
            pass

    # ── Form interactions ─────────────────────────────────────────────────────

    async def fill_first_name(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.FIRST_NAME_CFG, value, "first name")

    async def fill_last_name(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.LAST_NAME_CFG, value, "last name")

    async def fill_zip_code(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.ZIP_CODE_CFG, value, "zip code")

    async def submit(self) -> None:
        await self._resolve_and_click_any(self.Locators.CONTINUE_CFG, "continue button")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def cancel(self) -> None:
        await self._resolve_and_click_any(self.Locators.CANCEL_CFG, "cancel button")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        return await self._get_text_or_none(self.Locators.ERROR_MSG)
