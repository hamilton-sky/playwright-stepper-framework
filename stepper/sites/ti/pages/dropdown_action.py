"""sites/ti/pages/dropdown_action.py — Stepper glue for the-internet dropdown."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiDropdownPage(PageModule):
    site = "ti"

    class TiSelectDropdownAction(GlueAction):
        action_name = "ti_select_dropdown"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.dropdown_page import DropdownPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(DropdownPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                option = step.extra.get("option") or "Option 1"

                await pom.open()
                await pom.select_dropdown(option)

                logger.info("ti_select_dropdown ✓ — selected '%s'", option)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_select_dropdown failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.TiSelectDropdownAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
