"""
sites/pathly/pages/top_bar_action.py — Stepper glue for Pathly top bar.

JSON usage:
  { "action": "pathly_navigate_panel", "extra": { "panel": "flow" } }
  { "action": "pathly_toggle_chat" }
"""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlyTopBar(PageModule):
    site = "pathly"

    class PathlyNavigatePanelAction(GlueAction):
        """Switch to the flow, monitor or settings panel."""

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
                if not await topbar.navigate_to_panel(panel):
                    return StepResult(
                        step=step, status="failed",
                        error="pathly_navigate_panel: the element did not resolve on the "
                              "attached page — wrong screen, or the "
                              "data-testid is missing from Pathly Studio",
                    )
                return StepResult(step=step, status="passed")
            except ValueError as e:
                return StepResult(step=step, status="failed", error=str(e))
            except Exception as e:
                logger.error("pathly_navigate_panel failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyToggleChatAction(GlueAction):
        """Toggle the chat panel."""

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
                if not await topbar.toggle_chat():
                    return StepResult(
                        step=step, status="failed",
                        error="pathly_toggle_chat: the element did not resolve on the "
                              "attached page — wrong screen, or the "
                              "data-testid is missing from Pathly Studio",
                    )
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_toggle_chat failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(
            registry,
            cls.PathlyNavigatePanelAction(),
            cls.PathlyToggleChatAction(),
        )
