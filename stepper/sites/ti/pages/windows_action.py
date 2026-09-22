"""sites/ti/pages/windows_action.py — Stepper glue for the-internet new window."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiWindowsPage(PageModule):
    site = "ti"

    class TiOpenNewWindowAction(GlueAction):
        """Open the new-window link and switch to the window it opens."""

        action_name = "ti_open_new_window"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.windows_page import WindowsPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(WindowsPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()

                async with page.context.expect_page() as new_page_info:
                    await pom.click_click_here()

                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded")
                logger.info("ti_open_new_window ✓ — new window at %s", new_page.url)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_open_new_window failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiOpenNewWindowAction())
