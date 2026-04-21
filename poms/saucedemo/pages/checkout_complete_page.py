"""
saucedemo/pages/checkout_complete_page.py — Pure POM for the order confirmation page.

Single responsibility: selectors and raw reads for the post-checkout success screen.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class CheckoutCompletePage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        HEADER       = ".complete-header"
        BODY_TEXT    = ".complete-text"
        PONY_EXPRESS = ".pony_express"

        # ── Interactive ───────────────────────────────────────────────────────
        BACK_HOME = Locator(
            role="button", name="Back Home",
            css="[data-test='back-to-products']",
            description="back to products button",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/checkout-complete.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.HEADER, timeout=15_000
            )
        except Exception:
            pass

    async def get_header_text(self) -> str:
        el = await self._driver.query_selector(self.Locators.HEADER)
        return (await el.inner_text()).strip() if el else ""

    async def get_body_text(self) -> str:
        el = await self._driver.query_selector(self.Locators.BODY_TEXT)
        return (await el.inner_text()).strip() if el else ""

    async def is_order_confirmed(self) -> bool:
        try:
            return await self._driver.locator_count(self.Locators.HEADER) > 0
        except Exception:
            return False

    async def go_back_home(self) -> None:
        await self._interact(self.Locators.BACK_HOME, "click")
        await self._driver.wait_for_load_state("domcontentloaded")
