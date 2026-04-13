"""
sites/saucedemo/pages/checkout_action.py — Stepper glue for SauceDemo checkout.

Exposes one action:
  sd_checkout — fill shipping info, review order, finish, verify confirmation

This is the full checkout flow (step 1 → step 2 → complete).
Shipping info comes from step.extra or testdata defaults.

No selectors here — they belong to CheckoutInfoPage / CheckoutOverviewPage /
CheckoutCompletePage.

JSON usage:
  { "action": "sd_checkout",
    "extra": {
      "first_name": "Test",
      "last_name":  "User",
      "zip":        "12345"
    } }
"""
from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)

_DEFAULT_SHIPPING = {"first_name": "Test", "last_name": "User", "zip": "12345"}


class SDCheckoutPage(PageModule):
    site = "sd"

    class SDCheckoutAction(ActionStrategy):
        """
        Complete the SauceDemo checkout flow from the cart page.

        Steps executed:
          1. Open cart page → proceed to checkout (step 1)
          2. Fill first name, last name, zip code → continue (step 2)
          3. Read order total for logging → finish
          4. Verify confirmation header is present

        Shipping info priority:
          step.extra["first_name"] / ["last_name"] / ["zip"]
          → falls back to _DEFAULT_SHIPPING constants

        Stores the order total in context.counts["order_total_cents"]
        (as integer cents to avoid float keys).

        JSON usage:
          { "action": "sd_checkout" }
          { "action": "sd_checkout",
            "extra": { "first_name": "Jane", "last_name": "Doe", "zip": "90210" } }
        """
        action_name = "sd_checkout"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.shared.driver import PlaywrightDriver
                from poms.saucedemo.pages.cart_page import CartPage
                from poms.saucedemo.pages.checkout_info_page import CheckoutInfoPage
                from poms.saucedemo.pages.checkout_overview_page import CheckoutOverviewPage
                from poms.saucedemo.pages.checkout_complete_page import CheckoutCompletePage

                settings = load_settings()
                driver   = PlaywrightDriver(page)

                shipping = {
                    "first_name": step.extra.get("first_name", _DEFAULT_SHIPPING["first_name"]),
                    "last_name":  step.extra.get("last_name",  _DEFAULT_SHIPPING["last_name"]),
                    "zip":        step.extra.get("zip",        _DEFAULT_SHIPPING["zip"]),
                }

                # ── Step 1: cart → checkout form ──────────────────────────────
                cart_page = CartPage(driver, settings.base_url,
                                     page=page, resolver=resolver)
                await cart_page.open()
                await cart_page.proceed_to_checkout()
                logger.info("sd_checkout — proceeded to checkout info page")

                # ── Step 2: fill shipping info ────────────────────────────────
                info_page = CheckoutInfoPage(driver, settings.base_url,
                                             page=page, resolver=resolver)
                await info_page.wait_for_ready()
                await info_page.fill_first_name(shipping["first_name"])
                await info_page.fill_last_name(shipping["last_name"])
                await info_page.fill_zip_code(shipping["zip"])
                await info_page.submit()
                logger.info("sd_checkout — shipping info submitted")

                # ── Step 3: review order → finish ─────────────────────────────
                overview_page = CheckoutOverviewPage(driver, settings.base_url,
                                                     page=page, resolver=resolver)
                await overview_page.wait_for_ready()
                total = await overview_page.get_total()
                if total is not None:
                    context.set_count("order_total_cents", int(total * 100))
                    logger.info("sd_checkout — order total: $%.2f", total)
                await overview_page.finish()

                # ── Step 4: verify confirmation ───────────────────────────────
                complete_page = CheckoutCompletePage(driver, settings.base_url,
                                                     page=page, resolver=resolver)
                await complete_page.wait_for_ready()
                if not await complete_page.is_order_confirmed():
                    header = await complete_page.get_header_text()
                    return StepResult(
                        step=step, status="failed",
                        error=f"sd_checkout: confirmation not found — header was {header!r}",
                    )

                header = await complete_page.get_header_text()
                logger.info("sd_checkout ✓ — order confirmed: %r", header)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_checkout failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.SDCheckoutAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
