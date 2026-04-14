"""
sites/saucedemo/pages/inventory_action.py — Stepper glue for SauceDemo inventory.

Exposes two actions:
  sd_add_to_cart   — add one or more products by name; stores names in context
  sd_sort_products — apply a sort option to the product list

No selectors here — they belong to InventoryPage.
No flow logic in the POM — it belongs here.

JSON usage:
  { "action": "sd_add_to_cart",
    "extra": { "products": ["Sauce Labs Backpack", "Sauce Labs Bike Light"] } }

  { "action": "sd_sort_products",
    "extra": { "sort": "lohi" } }
"""
from __future__ import annotations
import logging

from stepper.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule
from stepper.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class SDInventoryPage(PageModule):
    site = "sd"

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
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.inventory_page import InventoryPage

                settings       = load_settings()
                driver         = self._driver(page)
                inventory_page = self._build_pom(InventoryPage, driver, settings.base_url,
                                                 page=page, resolver=resolver)

                products = step.extra.get("products", [])
                if not products:
                    return StepResult(
                        step=step, status="failed",
                        error="sd_add_to_cart: step.extra['products'] is required",
                    )

                await inventory_page.open()

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
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.inventory_page import InventoryPage

                settings       = load_settings()
                driver         = self._driver(page)
                inventory_page = self._build_pom(InventoryPage, driver, settings.base_url,
                                                 page=page, resolver=resolver)

                sort_option = step.extra.get("sort", InventoryPage.SORT_NAME_ASC)
                await inventory_page.select_sort(sort_option)

                logger.info("sd_sort_products ✓ — sort set to '%s'", sort_option)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_sort_products failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action in [cls.SDAddToCartAction(), cls.SDSortProductsAction()]:
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
