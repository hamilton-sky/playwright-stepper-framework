"""
saucedemo/pages/inventory_page.py — Pure POM for the SauceDemo inventory page.

Single responsibility: selectors and raw interactions for the products list.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from poms.saucedemo.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


@dataclass
class ProductSummary:
    """Lightweight value object — name, price, and detail-page URL from the inventory."""
    name:  str
    price: float
    url:   str = ""


class InventoryPage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        TITLE           = ".title"
        CART_BADGE      = ".shopping_cart_badge"
        ITEM            = ".inventory_item"
        ITEM_NAME       = ".inventory_item_name"
        ITEM_PRICE      = ".inventory_item_price"
        ITEM_DESC       = ".inventory_item_desc"
        # ── Interactive (per-item — within-card, use css_candidates() in loops) ──
        ADD_TO_CART = Locator(
            role="button", name="Add to cart",
            css="button[data-test^='add-to-cart']",
            description="add to cart button (per-item)",
        )
        REMOVE_ITEM = Locator(
            role="button", name="Remove",
            css="button[data-test^='remove']",
            description="remove item from cart button (per-item)",
        )

        # ── Interactive (page-level) ──────────────────────────────────────────
        SORT_DROPDOWN = Locator(
            css="[data-test='product-sort-container']",
            css_fallbacks=["select.product_sort_container"],
            description="product sort dropdown",
        )
        CART_LINK = Locator(
            role="link", name="shopping cart",
            css=".shopping_cart_link",
            description="cart link",
        )
        BURGER_MENU = Locator(
            role="button", name="Open Menu",
            id="react-burger-menu-btn",
            description="burger menu button",
        )
        LOGOUT = Locator(
            role="link", name="Logout",
            id="logout_sidebar_link",
            description="logout link",
        )

    SORT_NAME_ASC   = "az"
    SORT_NAME_DESC  = "za"
    SORT_PRICE_ASC  = "lohi"
    SORT_PRICE_DESC = "hilo"

    @property
    def url(self) -> str:
        return f"{self.base_url}/inventory.html"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.ITEM, timeout=15_000
            )
        except Exception:
            pass

    # ── Sort ──────────────────────────────────────────────────────────────────

    async def select_sort(self, option: str) -> None:
        css = self.Locators.SORT_DROPDOWN.css
        if self._page:
            await self._page.select_option(css, option)
        else:
            await self._driver.evaluate(
                f"document.querySelector('{css}').value = '{option}';"
                f"document.querySelector('{css}').dispatchEvent(new Event('change'));"
            )
        logger.info("Sort option set to: %s", option)

    # ── Product reads ─────────────────────────────────────────────────────────

    async def get_all_products(self) -> list[ProductSummary]:
        items  = await self._driver.query_selector_all(self.Locators.ITEM)
        result = []
        for item in items:
            name_el  = await item.query_selector(self.Locators.ITEM_NAME)
            price_el = await item.query_selector(self.Locators.ITEM_PRICE)
            if not name_el or not price_el:
                continue
            name  = (await name_el.inner_text()).strip()
            price = (await price_el.inner_text()).strip().lstrip("$")
            href  = (await name_el.get_attribute("href")) or ""
            if href and not href.startswith("http"):
                href = f"{self.base_url.rstrip('/')}{href}"
            try:
                result.append(ProductSummary(name=name, price=float(price), url=href))
            except ValueError:
                logger.warning("Could not parse price %r for %r", price, name)
        return result

    async def get_product_names(self) -> list[str]:
        items = await self._driver.query_selector_all(self.Locators.ITEM_NAME)
        return [(await el.inner_text()).strip() for el in items]

    async def get_cart_item_count(self) -> int:
        try:
            el = await self._driver.query_selector(self.Locators.CART_BADGE)
            if el:
                return int((await el.inner_text()).strip())
        except Exception:
            pass
        return 0

    # ── Cart interactions ─────────────────────────────────────────────────────

    async def add_to_cart_by_name(self, product_name: str) -> bool:
        if not self._page:
            logger.warning("add_to_cart_by_name requires page= injection")
            return False
        items = self._page.locator(self.Locators.ITEM)
        count = await items.count()
        for i in range(count):
            item_root = items.nth(i)
            name_el   = item_root.locator(self.Locators.ITEM_NAME)
            if (await name_el.inner_text()).strip() != product_name:
                continue
            for css in self.Locators.ADD_TO_CART.css_candidates():
                try:
                    btn = item_root.locator(css)
                    if await btn.count() > 0:
                        await btn.first.click()
                        logger.info("Added to cart: %s (via %s)", product_name, css)
                        return True
                except Exception:
                    continue
        logger.warning("Product not found on inventory page: %s", product_name)
        return False

    async def remove_from_cart_by_name(self, product_name: str) -> bool:
        items = await self._driver.query_selector_all(self.Locators.ITEM)
        for item in items:
            name_el = await item.query_selector(self.Locators.ITEM_NAME)
            if not name_el:
                continue
            if (await name_el.inner_text()).strip() == product_name:
                for css in self.Locators.REMOVE_ITEM.css_candidates():
                    btn = await item.query_selector(css)
                    if btn:
                        await btn.click()
                        logger.info("Removed from cart: %s", product_name)
                        return True
        return False

    # ── Navigation ────────────────────────────────────────────────────────────

    async def go_to_cart(self) -> None:
        await self._interact(self.Locators.CART_LINK, "click")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def open_burger_menu(self) -> None:
        await self._interact(self.Locators.BURGER_MENU, "click")

    async def logout(self) -> None:
        await self.open_burger_menu()
        await self._driver.wait_for_selector(
            self.Locators.LOGOUT.css, timeout=5_000
        )
        await self._interact(self.Locators.LOGOUT, "click")
        await self._driver.wait_for_load_state("domcontentloaded")
