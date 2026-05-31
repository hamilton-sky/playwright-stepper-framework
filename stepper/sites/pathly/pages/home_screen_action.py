"""
sites/pathly/pages/home_screen_action.py — Stepper glue for Pathly home screen.

JSON usage:
  { "action": "pathly_open_project",    "extra": { "project_name": "MyProject" } }
  { "action": "pathly_new_project" }
  { "action": "pathly_assert_projects", "extra": { "expected_names": ["A", "B"] } }
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PathlyHomeScreen(PageModule):
    site = "pathly"

    class PathlyOpenProjectAction(GlueAction):
        action_name = "pathly_open_project"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            project_name = step.extra.get("project_name")
            if not project_name:
                return StepResult(
                    step=step, status="failed",
                    error="pathly_open_project: missing required extra field 'project_name'",
                )
            try:
                from poms.pathly.pages.home_screen_page import HomeScreenPage

                driver = self._driver(page)
                home = self._build_pom(
                    HomeScreenPage, driver, "electron://pathly-homescreen",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await home.open_project(project_name)
                return StepResult(step=step, status="passed")
            except ValueError as e:
                return StepResult(step=step, status="failed", error=str(e))
            except Exception as e:
                logger.error("pathly_open_project failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyNewProjectAction(GlueAction):
        action_name = "pathly_new_project"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.home_screen_page import HomeScreenPage

                driver = self._driver(page)
                home = self._build_pom(
                    HomeScreenPage, driver, "electron://pathly-homescreen",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                await home.click_new_project()
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_new_project failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    class PathlyAssertProjectsAction(GlueAction):
        action_name = "pathly_assert_projects"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.pathly.pages.home_screen_page import HomeScreenPage

                expected_names = step.extra.get("expected_names", [])
                driver = self._driver(page)
                home = self._build_pom(
                    HomeScreenPage, driver, "electron://pathly-homescreen",
                    page=page, resolver=resolver, behaviour=behaviour,
                )
                actual = await home.get_project_names()
                missing = [n for n in expected_names if n not in actual]
                if missing:
                    return StepResult(
                        step=step, status="failed",
                        error=f"pathly_assert_projects: missing projects: {missing}",
                    )
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error("pathly_assert_projects failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        for action_cls in (
            cls.PathlyOpenProjectAction,
            cls.PathlyNewProjectAction,
            cls.PathlyAssertProjectsAction,
        ):
            action = action_cls()
            registry.register(action)
            logger.debug("Registered action: %s", action.action_name)
