"""
saucedemo/pages/checkout_overview_page.py — Pure POM for checkout step two.

Single responsibility: order-summary selectors and raw reads.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class CheckoutOverviewPage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        TITLE      = ".title"
        CART_ITEM  = ".cart_item"
        ITEM_NAME  = ".inventory_item_name"
        ITEM_PRICE = ".inventory_item_price"
        SUBTOTAL   = ".summary_subtotal_label"
        TAX        = ".summary_tax_label"
        TOTAL      = ".summary_total_label"

        # ── Interactive ───────────────────────────────────────────────────────
        FINISH = Locator(
            role="button", name="Finish",
            css="[data-test='finish']",
            description="finish order button",
        )
        CANCEL = Locator(
            role="button", name="Cancel",
            css="[data-test='cancel']",
            description="cancel button",
        )

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
        try:
            el = await self._driver.query_selector(selector)
            if el:
                text   = (await el.inner_text()).strip()
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
        await self._interact(self.Locators.FINISH, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def cancel(self) -> None:
        await self._interact(self.Locators.CANCEL, "click")
        await self._driver.wait_for_load_state("domcontentloaded")
