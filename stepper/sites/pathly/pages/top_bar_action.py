"""
sites/pathly/pages/top_bar_action.py — Stepper glue for Pathly top bar.

JSON usage:
  { "action": "pathly_navigate_panel", "extra": { "panel": "flow" } }
  { "action": "pathly_toggle_chat" }
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlyTopBar(PageModule):
    site = "pathly"

    class PathlyNavigatePanelAction(GlueAction):
        action_name = "pathly_navigate_panel"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.top_bar_page import TopBarPage

                panel = step.extra.get("panel")
                driver = self._driver(page)
                topbar = self._build_pom(
                    TopBarPage, driver, "electron://pathly-topbar",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await topbar.navigate_to_panel(panel)
                return StepResult(step=step, status="passed")
            except ValueError as e:
                return StepResult(step=step, status="failed", error=str(e))
            except Exception as e:
                logger.error("pathly_navigate_panel failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyToggleChatAction(GlueAction):
        action_name = "pathly_toggle_chat"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.top_bar_page import TopBarPage

                driver = self._driver(page)
                topbar = self._build_pom(
                    TopBarPage, driver, "electron://pathly-topbar",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await topbar.toggle_chat()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_toggle_chat failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action_cls in (
            cls.PathlyNavigatePanelAction,
            cls.PathlyToggleChatAction,
        ):
            action = action_cls()
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
