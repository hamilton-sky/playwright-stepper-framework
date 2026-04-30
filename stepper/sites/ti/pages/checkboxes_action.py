"""sites/ti/pages/checkboxes_action.py — Stepper glue for the-internet checkboxes."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiCheckboxesPage(PageModule):
    site = "ti"

    class TiToggleCheckboxesAction(GlueAction):
        action_name = "ti_toggle_checkboxes"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.checkboxes_page import CheckboxesPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(CheckboxesPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()
                await pom.click_checkbox_1()
                await pom.click_checkbox_2()

                logger.info("ti_toggle_checkboxes ✓ — toggled both checkboxes")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_toggle_checkboxes failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.TiToggleCheckboxesAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
