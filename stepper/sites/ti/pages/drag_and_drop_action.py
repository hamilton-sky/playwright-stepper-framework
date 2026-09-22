"""sites/ti/pages/drag_and_drop_action.py — Stepper glue for the-internet drag and drop."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiDragAndDropPage(PageModule):
    site = "ti"

    class TiDragAndDropAction(GlueAction):
        """
        Drag column A onto column B and report the resulting order.

        HTML5 drag-and-drop, so this goes through Playwright's own drag_and_drop
        rather than the resolver cascade — there is no driver-level equivalent.
        """

        action_name = "ti_drag_and_drop"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.drag_and_drop_page import DragAndDropPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(DragAndDropPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()
                await pom.drag_a_onto_b()

                order = await pom.get_column_order()
                logger.info("ti_drag_and_drop ✓ — column order after drag: %s", order)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_drag_and_drop failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiDragAndDropAction())
