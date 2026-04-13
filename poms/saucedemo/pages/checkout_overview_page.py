"""
saucedemo/pages/checkout_overview_page.py — Pure POM for checkout step two.

Single responsibility: order-summary selectors and raw reads.

Checkout step 2 of 2: customer reviews items, pricing, tax, and total,
then finishes or cancels.

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class CheckoutOverviewPage(BasePage):

    class Locators:
        """All checkout-step-two selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        TITLE      = ".title"
        CART_ITEM  = ".cart_item"
        ITEM_NAME  = ".inventory_item_name"
        ITEM_PRICE = ".inventory_item_price"
        SUBTOTAL   = ".summary_subtotal_label"
        TAX        = ".summary_tax_label"
        TOTAL      = ".summary_total_label"

        # ── Interactive — cfg lists are the single source of truth ───────────
        FINISH_CFG = [
            {"css":  "[data-test='finish']",   "priority": 10},
            {"role": "button", "name": "Finish", "priority": 20},
        ]
        CANCEL_CFG = [
            {"css":  "[data-test='cancel']",   "priority": 10},
            {"role": "button", "name": "Cancel", "priority": 20},
        ]

    @property
    def url(self) -> str:
        return f"{self.base_url}/checkout-step-two.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.TOTAL, timeout=15_000
            )
        except Exception:
            pass

    # ── Summary reads ─────────────────────────────────────────────────────────

    async def get_item_names(self) -> list[str]:
        els = await self._driver.query_selector_all(self.Locators.ITEM_NAME)
        return [(await el.inner_text()).strip() for el in els]

    async def _parse_price_label(self, selector: str) -> float | None:
        """Extract the numeric value from a summary label like 'Item total: $29.99'."""
        try:
            el = await self._driver.query_selector(selector)
            if el:
                text = (await el.inner_text()).strip()
                amount = text.rsplit("$", 1)[-1]
                return float(amount)
        except Exception:
            pass
        return None

    async def get_subtotal(self) -> float | None:
        return await self._parse_price_label(self.Locators.SUBTOTAL)

    async def get_tax(self) -> float | None:
        return await self._parse_price_label(self.Locators.TAX)

    async def get_total(self) -> float | None:
        return await self._parse_price_label(self.Locators.TOTAL)

    # ── Navigation ────────────────────────────────────────────────────────────

    async def finish(self) -> None:
        await self._resolve_and_click_any(self.Locators.FINISH_CFG, "finish button")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def cancel(self) -> None:
        await self._resolve_and_click_any(self.Locators.CANCEL_CFG, "cancel button")
        await self._driver.wait_for_load_state("domcontentloaded")
