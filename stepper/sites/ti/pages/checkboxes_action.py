"""sites/ti/pages/checkboxes_action.py — Stepper glue for the-internet checkboxes."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiCheckboxesPage(PageModule):
    site = "ti"

    class TiToggleCheckboxesAction(GlueAction):
        """Toggle both checkboxes and report their resulting states."""

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
                if not await pom.click_checkbox_1():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_toggle_checkboxes: checkbox 1 was not clicked "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )
                if not await pom.click_checkbox_2():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_toggle_checkboxes: checkbox 2 was not clicked "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )

                logger.info("ti_toggle_checkboxes ✓ — toggled both checkboxes")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_toggle_checkboxes failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiToggleCheckboxesAction())
