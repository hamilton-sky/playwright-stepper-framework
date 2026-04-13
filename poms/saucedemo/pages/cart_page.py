"""
saucedemo/pages/cart_page.py — Pure POM for the SauceDemo cart page.

Single responsibility: selectors and raw interactions for the shopping cart.

Exposed interactions:
  - read cart item names and prices
  - remove an item by name
  - proceed to checkout
  - continue shopping

No flow logic, no assertions.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


@dataclass
class CartItem:
    """Value object — one line in the cart."""
    name:     str
    price:    float
    quantity: int


class CartPage(BasePage):

    class Locators:
        """All cart-page selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        TITLE         = ".title"
        CART_ITEM     = ".cart_item"
        ITEM_NAME     = ".inventory_item_name"
        ITEM_PRICE    = ".inventory_item_price"
        ITEM_QUANTITY = ".cart_quantity"
        # Used inside row.query_selector() — not an independent page-level click
        REMOVE_BTN    = "button[data-test^='remove']"

        # ── Interactive — cfg lists are the single source of truth ───────────
        CHECKOUT_CFG = [
            {"css":  "[data-test='checkout']",          "priority": 10},
            {"role": "button", "name": "Checkout",      "priority": 20},
        ]
        CONTINUE_SHOPPING_CFG = [
            {"css":  "[data-test='continue-shopping']",       "priority": 10},
            {"role": "button", "name": "Continue Shopping",   "priority": 20},
        ]

    @property
    def url(self) -> str:
        return f"{self.base_url}/cart.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.TITLE, timeout=15_000
            )
        except Exception:
            pass

    # ── Cart reads ────────────────────────────────────────────────────────────

    async def get_items(self) -> list[CartItem]:
        """Return all items currently in the cart."""
        rows   = await self._driver.query_selector_all(self.Locators.CART_ITEM)
        result = []
        for row in rows:
            name_el   = await row.query_selector(self.Locators.ITEM_NAME)
            price_el  = await row.query_selector(self.Locators.ITEM_PRICE)
            qty_el    = await row.query_selector(self.Locators.ITEM_QUANTITY)
            if not name_el or not price_el:
                continue
            name      = (await name_el.inner_text()).strip()
            price_raw = (await price_el.inner_text()).strip().lstrip("$")
            qty_raw   = (await qty_el.inner_text()).strip() if qty_el else "1"
            try:
                result.append(CartItem(
                    name=name,
                    price=float(price_raw),
                    quantity=int(qty_raw),
                ))
            except ValueError:
                logger.warning("Could not parse cart item: name=%r price=%r qty=%r",
                               name, price_raw, qty_raw)
        return result

    async def get_item_count(self) -> int:
        rows = await self._driver.query_selector_all(self.Locators.CART_ITEM)
        return len(rows)

    async def is_empty(self) -> bool:
        return await self.get_item_count() == 0

    # ── Cart interactions ─────────────────────────────────────────────────────

    async def remove_item_by_name(self, name: str) -> bool:
        """
        Click the Remove button for the named item.
        Returns True if found and clicked, False otherwise.
        """
        rows = await self._driver.query_selector_all(self.Locators.CART_ITEM)
        for row in rows:
            name_el = await row.query_selector(self.Locators.ITEM_NAME)
            if not name_el:
                continue
            if (await name_el.inner_text()).strip() == name:
                btn = await row.query_selector(self.Locators.REMOVE_BTN)
                if btn:
                    await btn.click()
                    logger.info("Removed from cart: %s", name)
                    return True
        logger.warning("Item not found in cart: %s", name)
        return False

    # ── Navigation ────────────────────────────────────────────────────────────

    async def proceed_to_checkout(self) -> None:
        await self._resolve_and_click_any(self.Locators.CHECKOUT_CFG, "checkout button")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def continue_shopping(self) -> None:
        await self._resolve_and_click_any(self.Locators.CONTINUE_SHOPPING_CFG, "continue shopping")
        await self._driver.wait_for_load_state("domcontentloaded")
