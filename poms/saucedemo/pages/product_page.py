"""
saucedemo/pages/product_page.py — Pure POM for the SauceDemo product detail page.

Single responsibility: selectors and raw interactions for a single product page.

Exposed interactions:
  - read product name, description, price
  - add to / remove from cart
  - navigate back to products list

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class ProductPage(BasePage):

    class Locators:
        """All product-detail selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        ITEM_NAME  = ".inventory_details_name"
        ITEM_DESC  = ".inventory_details_desc"
        ITEM_PRICE = ".inventory_details_price"
        # Used for state-check only (locator_count)
        REMOVE     = "button[data-test^='remove']"

        # ── Interactive — cfg lists are the single source of truth ───────────
        ADD_TO_CART_CFG = [
            {"css":  "button[data-test^='add-to-cart']",   "priority": 10},
            {"role": "button", "name": "Add to cart",      "priority": 20},
        ]
        REMOVE_CFG = [
            {"css":  "button[data-test^='remove']",        "priority": 10},
            {"role": "button", "name": "Remove",           "priority": 20},
        ]
        BACK_CFG = [
            {"css":  "[data-test='back-to-products']",     "priority": 10},
            {"role": "button", "name": "Back to products", "priority": 20},
        ]

    def __init__(self, driver, base_url: str, item_id: int | None = None,
                 page=None, resolver=None):
        super().__init__(driver, base_url, page=page, resolver=resolver)
        self._item_id = item_id

    @property
    def url(self) -> str:
        if self._item_id is not None:
            return f"{self.base_url}/inventory-item.html?id={self._item_id}"
        return f"{self.base_url}/inventory-item.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.ITEM_NAME, timeout=15_000
            )
        except Exception:
            pass

    # ── Product reads ─────────────────────────────────────────────────────────

    async def get_name(self) -> str:
        el = await self._driver.query_selector(self.Locators.ITEM_NAME)
        return (await el.inner_text()).strip() if el else ""

    async def get_description(self) -> str:
        el = await self._driver.query_selector(self.Locators.ITEM_DESC)
        return (await el.inner_text()).strip() if el else ""

    async def get_price(self) -> float | None:
        """Return the price as a float, stripping the leading '$'."""
        el = await self._driver.query_selector(self.Locators.ITEM_PRICE)
        if not el:
            return None
        raw = (await el.inner_text()).strip().lstrip("$")
        try:
            return float(raw)
        except ValueError:
            logger.warning("Could not parse price: %r", raw)
            return None

    async def is_in_cart(self) -> bool:
        """True if the Remove button (not Add to cart) is currently visible."""
        try:
            return await self._driver.locator_count(self.Locators.REMOVE) > 0
        except Exception:
            return False

    # ── Cart interactions ─────────────────────────────────────────────────────

    async def add_to_cart(self) -> None:
        await self._resolve_and_click_any(self.Locators.ADD_TO_CART_CFG, "add to cart")
        logger.info("Product added to cart from detail page (id=%s)", self._item_id)

    async def remove_from_cart(self) -> None:
        await self._resolve_and_click_any(self.Locators.REMOVE_CFG, "remove from cart")
        logger.info("Product removed from cart from detail page (id=%s)", self._item_id)

    # ── Navigation ────────────────────────────────────────────────────────────

    async def go_back(self) -> None:
        await self._resolve_and_click_any(self.Locators.BACK_CFG, "back to products")
        await self._driver.wait_for_load_state("domcontentloaded")
