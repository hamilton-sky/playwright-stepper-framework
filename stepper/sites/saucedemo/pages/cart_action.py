"""
sites/saucedemo/pages/cart_action.py — Stepper glue for the SauceDemo cart page.

Exposes one action:
  sd_view_cart — navigate to the cart and store item count in context.counts

No selectors here — they belong to CartPage.

JSON usage:
  { "action": "sd_view_cart" }
"""
from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class SDCartPage(PageModule):
    site = "sd"

    class SDViewCartAction(ActionStrategy):
        """
        Navigate to the cart page and record how many items are present.

        Stores the count in context.counts["cart_item_count"] so downstream
        steps or when-conditions can assert on it.

        JSON usage:
          { "action": "sd_view_cart" }
        """
        action_name = "sd_view_cart"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.shared.driver import PlaywrightDriver
                from poms.saucedemo.pages.cart_page import CartPage

                settings  = load_settings()
                driver    = PlaywrightDriver(page)
                cart_page = CartPage(driver, settings.base_url,
                                    page=page, resolver=resolver)

                await cart_page.open()
                items = await cart_page.get_items()
                count = len(items)

                context.set_count("cart_item_count", count)
                logger.info(
                    "sd_view_cart ✓ — %d item(s) in cart: %s",
                    count, [i.name for i in items],
                )
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_view_cart failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.SDViewCartAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
