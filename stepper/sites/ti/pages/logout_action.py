"""sites/ti/pages/logout_action.py — Stepper glue for the-internet logout."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiLogoutPage(PageModule):
    site = "ti"

    class TiLogoutAction(GlueAction):
        """Log out of the secure area and confirm the flash message."""

        action_name = "ti_logout"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.secure_page import SecurePage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(SecurePage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.wait_for_ready()
                if not await pom.click_logout():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_logout: the Logout link was not clicked — the "
                              "element did not resolve on the page, or it is "
                              "present but not interactable",
                    )

                # Its docstring says "and confirm the flash message", so confirm
                # it. the-internet redirects to /login and renders
                # "You logged out of the secure area!" there; landing anywhere
                # else means the click went somewhere unexpected.
                await page.wait_for_load_state("domcontentloaded")
                flash = await pom.get_flash_message()
                if not flash:
                    return StepResult(
                        step=step, status="failed",
                        error="ti_logout: clicked Logout but no confirmation flash "
                              f"followed (url: {page.url})",
                    )

                logger.info("ti_logout ✓ — %s", flash)
                return StepResult(step=step, status="passed",
                                  output={"ti_logout_flash": flash})

            except Exception as e:
                logger.error("ti_logout failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiLogoutAction())
