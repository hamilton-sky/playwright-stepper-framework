"""sites/ti/pages/logout_action.py — Stepper glue for the-internet logout."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiLogoutPage(PageModule):
    site = "ti"

    class TiLogoutAction(GlueAction):
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
                await pom.click_logout()

                logger.info("ti_logout ✓ — logged out from secure area")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_logout failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.TiLogoutAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
