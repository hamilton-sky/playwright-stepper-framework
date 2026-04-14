"""
saucedemo/pages/checkout_complete_page.py — Pure POM for the order confirmation page.

Single responsibility: selectors and raw reads for the post-checkout success screen.

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class CheckoutCompletePage(BasePage):

    class Locators:
        """All checkout-complete selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        HEADER       = ".complete-header"
        BODY_TEXT    = ".complete-text"
        PONY_EXPRESS = ".pony_express"   # delivery image

        # ── Interactive — cfg list is the single source of truth ─────────────
        BACK_HOME_CFG = [
            {"css":  "[data-test='back-to-products']",      "priority": 10},
            {"role": "button", "name": "Back Home",          "priority": 20},
        ]

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

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_header_text(self) -> str:
        el = await self._driver.query_selector(self.Locators.HEADER)
        return (await el.inner_text()).strip() if el else ""

    async def get_body_text(self) -> str:
        el = await self._driver.query_selector(self.Locators.BODY_TEXT)
        return (await el.inner_text()).strip() if el else ""

    async def is_order_confirmed(self) -> bool:
        """True if the confirmation header is present."""
        try:
            return await self._driver.locator_count(self.Locators.HEADER) > 0
        except Exception:
            return False

    # ── Navigation ────────────────────────────────────────────────────────────

    async def go_back_home(self) -> None:
        await self._resolve_and_click_any(self.Locators.BACK_HOME_CFG, "back to products")
        await self._driver.wait_for_load_state("domcontentloaded")
