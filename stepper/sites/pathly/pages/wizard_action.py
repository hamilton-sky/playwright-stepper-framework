"""
sites/pathly/pages/wizard_action.py — Stepper glue for the Pathly FlowWizard.

JSON usage:
  { "action": "pathly_open_wizard" }
  { "action": "pathly_wizard_select_template", "extra": { "template_id": "standard-pipeline" } }
  { "action": "pathly_wizard_set_name",        "extra": { "name": "my-flow" } }
  { "action": "pathly_wizard_next" }
  { "action": "pathly_wizard_save" }
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlyWizard(PageModule):
    site = "pathly"

    class PathlyOpenWizardAction(GlueAction):
        action_name = "pathly_open_wizard"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.wizard_page import WizardPage

                driver = self._driver(page)
                wizard = self._build_pom(
                    WizardPage, driver, "electron://pathly-wizard",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await wizard.open_wizard()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_open_wizard failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyWizardSelectTemplateAction(GlueAction):
        action_name = "pathly_wizard_select_template"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            template_id = step.extra.get("template_id")
            if not template_id:
                return StepResult(
                    step=step, status="failed",
                    error="pathly_wizard_select_template: missing required extra field 'template_id'",
                )
            try:
                from poms.pathly.pages.wizard_page import WizardPage

                driver = self._driver(page)
                wizard = self._build_pom(
                    WizardPage, driver, "electron://pathly-wizard",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await wizard.select_template(template_id)
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_wizard_select_template failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyWizardSetNameAction(GlueAction):
        action_name = "pathly_wizard_set_name"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            name = step.extra.get("name") or step.extra.get("flow_name")
            if not name:
                return StepResult(
                    step=step, status="failed",
                    error="pathly_wizard_set_name: missing required field 'name' in extra",
                )
            try:
                from poms.pathly.pages.wizard_page import WizardPage

                driver = self._driver(page)
                wizard = self._build_pom(
                    WizardPage, driver, "electron://pathly-wizard",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await wizard.set_name(name)
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_wizard_set_name failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyWizardNextAction(GlueAction):
        action_name = "pathly_wizard_next"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.wizard_page import WizardPage

                driver = self._driver(page)
                wizard = self._build_pom(
                    WizardPage, driver, "electron://pathly-wizard",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await wizard.click_next()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_wizard_next failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyWizardSaveAction(GlueAction):
        action_name = "pathly_wizard_save"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.wizard_page import WizardPage

                driver = self._driver(page)
                wizard = self._build_pom(
                    WizardPage, driver, "electron://pathly-wizard",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await wizard.click_save()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_wizard_save failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action_cls in (
            cls.PathlyOpenWizardAction,
            cls.PathlyWizardSelectTemplateAction,
            cls.PathlyWizardSetNameAction,
            cls.PathlyWizardNextAction,
            cls.PathlyWizardSaveAction,
        ):
            action = action_cls()
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
