"""sites/ti/pages/hovers_action.py — Stepper glue for the-internet hovers."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiHoversPage(PageModule):
    site = "ti"

    class TiHoverUserAction(GlueAction):
        action_name = "ti_hover_user"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.hovers_page import HoversPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(HoversPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()
                await pom.hover_user_avatar_1()
                await pom.click_view_profile_1()

                logger.info("ti_hover_user ✓ — hovered avatar and clicked profile link")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_hover_user failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.TiHoverUserAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
