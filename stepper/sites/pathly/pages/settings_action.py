"""
sites/pathly/pages/settings_action.py — Stepper glue for Pathly settings page.

JSON usage:
  { "action": "pathly_set_routing", "extra": { "engine": "llm" } }
  { "action": "pathly_save_settings" }
"""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlySettings(PageModule):
    site = "pathly"

    class PathlySetRoutingAction(GlueAction):
        """Select the routing engine in settings."""

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
                if not await settings.set_routing_engine(engine):
                    return StepResult(
                        step=step, status="failed",
                        error="pathly_set_routing: the element did not resolve on the "
                              "attached page — wrong screen, or the "
                              "data-testid is missing from Pathly Studio",
                    )
                return StepResult(step=step, status="passed")
            except ValueError as e:
                return StepResult(step=step, status="failed", error=str(e))
            except Exception as e:
                logger.error("pathly_set_routing failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyReadRoutingAction(GlueAction):
        """Read the selected routing engine into the context."""

        action_name = "pathly_read_routing"
        read_only   = True

        #: Where the value lands when the step does not name a key. A later
        #: step reads it back as `{{pathly_routing_engine}}` — context.store
        #: writes the generic _data map, which is what context_lookup reads.
        DEFAULT_KEY = "pathly_routing_engine"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            key = step.extra.get("key") or self.DEFAULT_KEY
            try:
                from poms.pathly.pages.settings_page import SettingsPage

                driver = self._driver(page)
                settings = self._build_pom(
                    SettingsPage, driver, "electron://pathly-settings",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                engine = await settings.get_routing_engine()
                # The docstring says "into the context", so put it there — and
                # into output, so it also reaches results.json. StoreAction does
                # both for the same reason; a read nobody can reach is a log line.
                context.store(key, engine)
                logger.info("✓ pathly_read_routing: %s=%r", key, engine)
                return StepResult(step=step, status="passed", output={key: engine})
            except Exception as e:
                logger.error("pathly_read_routing failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlySaveSettingsAction(GlueAction):
        """Save the settings panel."""

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
                if not await settings.save_settings():
                    return StepResult(
                        step=step, status="failed",
                        error="pathly_save_settings: the element did not resolve on the "
                              "attached page — wrong screen, or the "
                              "data-testid is missing from Pathly Studio",
                    )
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_save_settings failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(
            registry,
            cls.PathlySetRoutingAction(),
            cls.PathlySaveSettingsAction(),
            cls.PathlyReadRoutingAction(),
        )
