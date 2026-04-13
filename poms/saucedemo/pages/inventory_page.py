"""
saucedemo/pages/inventory_page.py — Pure POM for the SauceDemo inventory page.

Single responsibility: selectors and raw interactions for the products list.

Exposed interactions:
  - sort products by a given option
  - collect all visible product names and prices
  - add a product to cart by name
  - remove a product from cart by name
  - navigate to cart

No flow logic, no assertions, no loops across pages.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from poms.saucedemo.pages.base_page import BasePage

logger = logging.getLogger(__name__)


@dataclass
class ProductSummary:
    """Lightweight value object — name + price as read from the inventory page."""
    name:  str
    price: float


class InventoryPage(BasePage):

    class Locators:
        """All inventory-page selectors. Never duplicated elsewhere."""
        # ── Read-only ────────────────────────────────────────────────────────
        TITLE         = ".title"
        CART_BADGE    = ".shopping_cart_badge"
        ITEM          = ".inventory_item"
        ITEM_NAME     = ".inventory_item_name"
        ITEM_PRICE    = ".inventory_item_price"
        ITEM_DESC     = ".inventory_item_desc"
        # Used inside item.query_selector() — not independent page-level clicks
        ADD_TO_CART_BTN = "button[data-test^='add-to-cart']"
        REMOVE_BTN      = "button[data-test^='remove']"

        # ── Interactive — cfg lists are the single source of truth ───────────
        SORT_DROPDOWN_CFG = [
            {"css": "[data-test='product-sort-container']", "priority": 10},
            {"css": "select.product_sort_container",        "priority": 20},
        ]
        CART_LINK_CFG = [
            {"css":  ".shopping_cart_link",              "priority": 10},
            {"role": "link", "name": "shopping cart",    "priority": 20},
        ]
        BURGER_MENU_CFG = [
            {"css": "#react-burger-menu-btn",            "priority": 10},
            {"role": "button", "name": "Open Menu",      "priority": 20},
        ]
        LOGOUT_CFG = [
            {"css":  "#logout_sidebar_link",             "priority": 10},
            {"role": "link", "name": "Logout",           "priority": 20},
        ]

    # Sort option values accepted by the <select> element
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
        """
        Select a sort option from the dropdown.
        Use the SORT_* class constants or pass the raw option value directly.
        """
        page = self._page
        if page:
            css = self.Locators.SORT_DROPDOWN_CFG[0]["css"]
            await page.select_option(css, option)
        else:
            # driver-level fallback via JS evaluate
            css = self.Locators.SORT_DROPDOWN_CFG[0]["css"]
            await self._driver.evaluate(
                f"document.querySelector('{css}').value = '{option}';"
                f"document.querySelector('{css}').dispatchEvent(new Event('change'));"
            )
        logger.info("Sort option set to: %s", option)

    # ── Product reads ─────────────────────────────────────────────────────────

    async def get_all_products(self) -> list[ProductSummary]:
        """Return name + price for every visible product card."""
        items  = await self._driver.query_selector_all(self.Locators.ITEM)
        result = []
        for item in items:
            name_el  = await item.query_selector(self.Locators.ITEM_NAME)
            price_el = await item.query_selector(self.Locators.ITEM_PRICE)
            if not name_el or not price_el:
                continue
            name  = (await name_el.inner_text()).strip()
            price = (await price_el.inner_text()).strip().lstrip("$")
            try:
                result.append(ProductSummary(name=name, price=float(price)))
            except ValueError:
                logger.warning("Could not parse price %r for %r", price, name)
        return result

    async def get_product_names(self) -> list[str]:
        """Return just the visible product names, in DOM order."""
        items = await self._driver.query_selector_all(self.Locators.ITEM_NAME)
        return [(await el.inner_text()).strip() for el in items]

    async def get_cart_item_count(self) -> int:
        """Return the number shown on the cart badge (0 if badge not visible)."""
        try:
            el = await self._driver.query_selector(self.Locators.CART_BADGE)
            if el:
                return int((await el.inner_text()).strip())
        except Exception:
            pass
        return 0

    # ── Cart interactions ─────────────────────────────────────────────────────

    async def add_to_cart_by_name(self, product_name: str) -> bool:
        """
        Click the 'Add to cart' button for the item whose name matches exactly.
        Returns True if clicked, False if the item was not found.
        """
        items = await self._driver.query_selector_all(self.Locators.ITEM)
        for item in items:
            name_el = await item.query_selector(self.Locators.ITEM_NAME)
            if not name_el:
                continue
            if (await name_el.inner_text()).strip() == product_name:
                btn = await item.query_selector(self.Locators.ADD_TO_CART_BTN)
                if btn:
                    await btn.click()
                    logger.info("Added to cart: %s", product_name)
                    return True
        logger.warning("Product not found on inventory page: %s", product_name)
        return False

    async def remove_from_cart_by_name(self, product_name: str) -> bool:
        """
        Click the 'Remove' button for the named item.
        Returns True if clicked, False if not found.
        """
        items = await self._driver.query_selector_all(self.Locators.ITEM)
        for item in items:
            name_el = await item.query_selector(self.Locators.ITEM_NAME)
            if not name_el:
                continue
            if (await name_el.inner_text()).strip() == product_name:
                btn = await item.query_selector(self.Locators.REMOVE_BTN)
                if btn:
                    await btn.click()
                    logger.info("Removed from cart: %s", product_name)
                    return True
        return False

    # ── Navigation ────────────────────────────────────────────────────────────

    async def go_to_cart(self) -> None:
        await self._resolve_and_click_any(self.Locators.CART_LINK_CFG, "cart link")
        await self._driver.wait_for_load_state("domcontentloaded")

    async def open_burger_menu(self) -> None:
        await self._resolve_and_click_any(self.Locators.BURGER_MENU_CFG, "burger menu")

    async def logout(self) -> None:
        """Open the burger menu then click the logout link."""
        await self.open_burger_menu()
        await self._driver.wait_for_selector(
            self.Locators.LOGOUT_CFG[0]["css"], timeout=5_000
        )
        await self._resolve_and_click_any(self.Locators.LOGOUT_CFG, "logout link")
        await self._driver.wait_for_load_state("domcontentloaded")
