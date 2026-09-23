"""sites/ti/pages/hovers_action.py — Stepper glue for the-internet hovers."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiHoversPage(PageModule):
    site = "ti"

    class TiHoverUserAction(GlueAction):
        """Hover each avatar and read the caption it reveals."""

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
                if not await pom.hover_user_avatar_1():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_hover_user: the first avatar was not there to hover "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )
                if not await pom.click_view_profile_1():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_hover_user: the revealed profile link was not clicked "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )

                logger.info("ti_hover_user ✓ — hovered avatar and clicked profile link")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_hover_user failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiHoverUserAction())
