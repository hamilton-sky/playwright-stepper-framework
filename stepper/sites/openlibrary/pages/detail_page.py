"""
sites/openlibrary/pages/detail_page.py — Stepper action module for OL book detail.

Wires the exam's BookDetailPage into the Stepper ActionRegistry.
Dependency direction: sites.openlibrary → stepper  (correct)
                      sites.openlibrary → openlibrary  (correct)
"""

from __future__ import annotations
import logging
import warnings

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class OLDetailPage(PageModule):
    site = "ol"
    # Selectors removed — owned by BookDetailPage.Locators (Option 3).
    # Glue layers never duplicate POM selector knowledge.

    class OLAddToShelfAction(ActionStrategy):
        """
        Iterate over context.collected_items, open each book page,
        click the shelf button, take a screenshot.

        JSON usage:
          { "action": "ol_add_to_shelf" }
        """
        action_name = "ol_add_to_shelf"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.pages.book_detail_page import BookDetailPage

                settings        = load_settings()
                driver          = PlaywrightDriver(page)
                # Use openlibrary's own screenshot directory (self-contained module)
                screenshots_dir = settings.screenshots_dir
                screenshots_dir.mkdir(parents=True, exist_ok=True)

                urls = context.collected_items
                if not urls:
                    return StepResult(
                        step=step, status="skipped",
                        error="context.collected_items is empty"
                    )

                all_screenshots: list[str] = []
                for idx, url in enumerate(urls, start=1):
                    detail = BookDetailPage(
                        driver, settings.base_url, url, settings.delays,
                        page=page, resolver=resolver,
                    )
                    await detail.open()

                    added = await detail.add_to_reading_list()
                    if not added:
                        warnings.warn(
                            f"Could not shelve book {url} — may already be on list",
                            stacklevel=2,
                        )

                    shot_path = str(screenshots_dir / f"book_{idx}.png")
                    await driver.screenshot(path=shot_path)
                    all_screenshots.append(shot_path)
                    logger.info(f"ol_add_to_shelf [{idx}/{len(urls)}] → {'added' if added else 'skipped'}")

                return StepResult(
                    step=step, status="passed",
                    screenshot=all_screenshots[-1] if all_screenshots else "",
                    screenshots=all_screenshots,
                )

            except Exception as e:
                logger.error(f"ol_add_to_shelf failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        actions = [cls.OLAddToShelfAction()]
        for action in actions:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(
                    f"{action.__class__.__name__}.action_name must start with "
                    f"'{cls.site}_', got '{action.action_name}'"
                )
            registry.register(action)
            logger.debug(f"Registered page action: {action.action_name}")
