"""
saucedemo/pages/checkout_info_page.py — Pure POM for checkout step one.

Single responsibility: shipping-info form selectors and raw interactions.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class CheckoutInfoPage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        TITLE     = ".title"
        ERROR_MSG = "[data-test='error']"

        # ── Interactive ───────────────────────────────────────────────────────
        FIRST_NAME = Locator(
            placeholder="First Name",
            css="[data-test='firstName']",
            description="first name field",
        )
        LAST_NAME = Locator(
            placeholder="Last Name",
            css="[data-test='lastName']",
            description="last name field",
        )
        ZIP_CODE = Locator(
            placeholder="Zip/Postal Code",
            css="[data-test='postalCode']",
            description="zip/postal code field",
        )
        CONTINUE = Locator(
            role="button", name="Continue",
            css="[data-test='continue']",
            description="continue button",
        )
        CANCEL = Locator(
            role="button", name="Cancel",
            css="[data-test='cancel']",
            description="cancel button",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/checkout-step-one.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.FIRST_NAME.css, timeout=15_000
            )
        except Exception:
            pass

    # ── Form interactions ─────────────────────────────────────────────────────

    async def fill_first_name(self, value: str) -> None:
        await self._interact(self.Locators.FIRST_NAME, "fill", value=value)

    async def fill_last_name(self, value: str) -> None:
        await self._interact(self.Locators.LAST_NAME, "fill", value=value)

    async def fill_zip_code(self, value: str) -> None:
        await self._interact(self.Locators.ZIP_CODE, "fill", value=value)

    async def submit(self) -> None:
        await self._interact(self.Locators.CONTINUE, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def cancel(self) -> None:
        await self._interact(self.Locators.CANCEL, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def get_error_message(self) -> str | None:
        return await self._get_text_or_none(self.Locators.ERROR_MSG)
