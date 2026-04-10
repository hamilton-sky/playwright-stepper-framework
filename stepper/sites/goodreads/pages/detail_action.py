from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class GRDetailPage(PageModule):
    site = "gr"

    class GRAddToShelfAction(ActionStrategy):
        action_name = "gr_add_to_shelf"

        async def _execute(self, page, step: StepConfig, resolver, context: ExecutionContext) -> StepResult:
            try:
                from goodreads.config import load_settings
                from goodreads.driver import PlaywrightDriver
                from goodreads.pages.detail_page import GoodreadsDetailPage

                settings = load_settings()
                driver = PlaywrightDriver(page)

                urls = context.collected_items
                if not urls:
                    return StepResult(step=step, status="skipped", error="context.collected_items is empty")

                for idx, url in enumerate(urls, start=1):
                    pom = GoodreadsDetailPage(driver, settings.base_url, url, settings.delays, page=page, resolver=resolver)
                    await pom.open()
                    await pom.add_to_shelf()
                    logger.info(f"gr_add_to_shelf [{idx}/{len(urls)}] -> added")

                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error(f"gr_add_to_shelf failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        actions = [cls.GRAddToShelfAction()]
        for action in actions:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(
                    f"{action.__class__.__name__}.action_name must start with '{cls.site}_', got '{action.action_name}'"
                )
            registry.register(action)
            logger.debug(f"Registered page action: {action.action_name}")
