"""
sites/pathly/pages/settings_action.py — Stepper glue for Pathly settings page.

JSON usage:
  { "action": "pathly_set_routing", "extra": { "engine": "llm" } }
  { "action": "pathly_save_settings" }
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlySettings(PageModule):
    site = "pathly"

    class PathlySetRoutingAction(GlueAction):
        action_name = "pathly_set_routing"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.settings_page import SettingsPage

                engine = step.extra.get("engine")
                driver = self._driver(page)
                settings = self._build_pom(
                    SettingsPage, driver, "electron://pathly-settings",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await settings.set_routing_engine(engine)
                return StepResult(step=step, status="passed")
            except ValueError as e:
                return StepResult(step=step, status="failed", error=str(e))
            except Exception as e:
                logger.error("pathly_set_routing failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyReadRoutingAction(GlueAction):
        action_name = "pathly_read_routing"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.settings_page import SettingsPage

                driver = self._driver(page)
                settings = self._build_pom(
                    SettingsPage, driver, "electron://pathly-settings",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                engine = await settings.get_routing_engine()
                logger.info("pathly_read_routing: current engine = %s", engine)
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_read_routing failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlySaveSettingsAction(GlueAction):
        action_name = "pathly_save_settings"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.settings_page import SettingsPage

                driver = self._driver(page)
                settings = self._build_pom(
                    SettingsPage, driver, "electron://pathly-settings",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await settings.save_settings()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_save_settings failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action_cls in (
            cls.PathlySetRoutingAction,
            cls.PathlySaveSettingsAction,
            cls.PathlyReadRoutingAction,
        ):
            action = action_cls()
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
