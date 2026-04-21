"""
saucedemo/pages/product_page.py — Pure POM for the SauceDemo product detail page.

Single responsibility: selectors and raw interactions for a single product page.
"""
from __future__ import annotations
import logging

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class ProductPage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        ITEM_NAME  = ".inventory_details_name"
        ITEM_DESC  = ".inventory_details_desc"
        ITEM_PRICE = ".inventory_details_price"
        REMOVE     = "button[data-test^='remove']"

        # ── Interactive ───────────────────────────────────────────────────────
        ADD_TO_CART = Locator(
            role="button", name="Add to cart",
            css="button[data-test^='add-to-cart']",
            description="add to cart button",
        )
        REMOVE_FROM_CART = Locator(
            role="button", name="Remove",
            css="button[data-test^='remove']",
            description="remove from cart button",
        )
        BACK = Locator(
            role="button", name="Back to products",
            css="[data-test='back-to-products']",
            description="back to products button",
        )

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

    async def get_name(self) -> str:
        el = await self._driver.query_selector(self.Locators.ITEM_NAME)
        return (await el.inner_text()).strip() if el else ""

    async def get_description(self) -> str:
        el = await self._driver.query_selector(self.Locators.ITEM_DESC)
        return (await el.inner_text()).strip() if el else ""

    async def get_price(self) -> float | None:
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
        try:
            return await self._driver.locator_count(self.Locators.REMOVE) > 0
        except Exception:
            return False

    async def add_to_cart(self) -> None:
        await self._interact(self.Locators.ADD_TO_CART, "click")
        logger.info("Product added to cart from detail page (id=%s)", self._item_id)

    async def remove_from_cart(self) -> None:
        await self._interact(self.Locators.REMOVE_FROM_CART, "click")
        logger.info("Product removed from cart from detail page (id=%s)", self._item_id)

    async def go_back(self) -> None:
        await self._interact(self.Locators.BACK, "click")
        await self._driver.wait_for_load_state("domcontentloaded")
