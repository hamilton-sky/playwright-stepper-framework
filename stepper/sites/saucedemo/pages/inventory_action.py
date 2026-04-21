"""
sites/saucedemo/pages/inventory_action.py — Stepper glue for SauceDemo inventory.

Exposes three actions:
  sd_collect_products — collect all product names, prices, and URLs into context
  sd_add_to_cart      — add one or more products by name; stores names in context
  sd_sort_products    — apply a sort option to the product list

No selectors here — they belong to InventoryPage.
No flow logic in the POM — it belongs here.

JSON usage:
  { "action": "sd_collect_products" }

  { "action": "sd_add_to_cart",
    "extra": { "products": ["Sauce Labs Backpack", "Sauce Labs Bike Light"] } }

  { "action": "sd_sort_products",
    "extra": { "sort": "lohi" } }
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class SDInventoryPage(PageModule):
    site = "sd"

    class SDCollectProductsAction(GlueAction):
        """
        Collect all visible products (name, price, URL) from the inventory page.
        Stores the list in context.extracted_data as dicts with keys
        "name", "price", "url".  Also writes the count to step output.

        JSON usage:
          { "action": "sd_collect_products" }
        """
        action_name = "sd_collect_products"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
            behaviour=None,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.inventory_page import InventoryPage

                settings       = load_settings()
                driver         = self._driver(page)
                inventory_page = self._build_pom(
                    InventoryPage, driver, settings.base_url,
                    page=page, resolver=resolver, behaviour=behaviour,
                )

                products = await inventory_page.get_all_products()

                f = step.extra.get("filter", {})
                if "price_max" in f:
                    products = [p for p in products if p.price <= float(f["price_max"])]
                if "price_min" in f:
                    products = [p for p in products if p.price >= float(f["price_min"])]

                limit = step.extra.get("limit")
                if limit is not None:
                    products = products[: int(limit)]

                context.extracted_data = [
                    {"name": p.name, "price": p.price, "url": p.url}
                    for p in products
                ]
                logger.info("sd_collect_products ✓ — collected %d products", len(products))
                return StepResult(
                    step=step, status="passed",
                    output={"count": len(products), "products": context.extracted_data},
                )

            except Exception as e:
                logger.error("sd_collect_products failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class SDAddToCartAction(GlueAction):
        """
        Navigate to the inventory page and add each named product to the cart.

        Products come from step.extra["products"] (list of exact product names).
        After adding, stores the names in context.collected_items so downstream
        steps (e.g. sd_checkout) can reference what was ordered.

        JSON usage:
          { "action": "sd_add_to_cart",
            "extra": { "products": ["Sauce Labs Backpack"] } }
        """
        action_name = "sd_add_to_cart"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.inventory_page import InventoryPage

                settings       = load_settings()
                driver         = self._driver(page)
                inventory_page = self._build_pom(
                    InventoryPage, driver, settings.base_url,
                    page=page, resolver=resolver, behaviour=behaviour,
                )

                products = step.extra.get("products") or [
                    item["name"] for item in (context.extracted_data or [])
                ]
                if not products:
                    return StepResult(
                        step=step, status="failed",
                        error="sd_add_to_cart: no products — set step.extra['products'] or run sd_collect_products first",
                    )

                added: list[str] = []
                failed: list[str] = []
                for name in products:
                    ok = await inventory_page.add_to_cart_by_name(name)
                    if ok:
                        added.append(name)
                    else:
                        failed.append(name)

                context.collected_items = added
                logger.info("sd_add_to_cart ✓ — added %d/%d products", len(added), len(products))

                if failed:
                    logger.warning("sd_add_to_cart — not found on page: %s", failed)
                    return StepResult(
                        step=step, status="failed",
                        error=f"sd_add_to_cart: products not found: {failed}",
                    )

                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_add_to_cart failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class SDSortProductsAction(GlueAction):
        """
        Apply a sort option to the inventory product list.

        Sort values (pass as step.extra["sort"]):
          "az"   — Name (A to Z)
          "za"   — Name (Z to A)
          "lohi" — Price (low to high)
          "hilo" — Price (high to low)

        JSON usage:
          { "action": "sd_sort_products", "extra": { "sort": "lohi" } }
        """
        action_name = "sd_sort_products"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.inventory_page import InventoryPage

                settings       = load_settings()
                driver         = self._driver(page)
                inventory_page = self._build_pom(
                    InventoryPage, driver, settings.base_url,
                    page=page, resolver=resolver, behaviour=behaviour,
                )

                sort_option = step.extra.get("sort", InventoryPage.SORT_NAME_ASC)
                await inventory_page.select_sort(sort_option)

                logger.info("sd_sort_products ✓ — sort set to '%s'", sort_option)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_sort_products failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action in [
            cls.SDCollectProductsAction(),
            cls.SDAddToCartAction(),
            cls.SDSortProductsAction(),
        ]:
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
