from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class GRSearchPage(PageModule):
    site = "gr"

    class GRCollectItemsAction(ActionStrategy):
        action_name = "gr_collect_items"
        read_only = True

        async def _execute(self, page, step: StepConfig, resolver, context: ExecutionContext) -> StepResult:
            try:
                from goodreads.config import load_settings
                from goodreads.driver import PlaywrightDriver
                from goodreads.pages.search_page import GoodreadsSearchPage

                settings = load_settings()
                driver = PlaywrightDriver(page)
                pom = GoodreadsSearchPage(driver, settings.base_url, settings.delays)

                query = step.extra.get("query", "")
                limit = step.extra.get("limit", 5)

                await pom.open()
                await pom.search(query)
                urls = await pom.collect_items(limit=limit)

                context.collected_items = urls
                logger.info(f"gr_collect_items -> collected {len(urls)} items")
                return StepResult(step=step, status="passed")
            except Exception as e:
                logger.error(f"gr_collect_items failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        actions = [cls.GRCollectItemsAction()]
        for action in actions:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(
                    f"{action.__class__.__name__}.action_name must start with '{cls.site}_', got '{action.action_name}'"
                )
            registry.register(action)
            logger.debug(f"Registered page action: {action.action_name}")
