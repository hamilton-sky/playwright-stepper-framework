"""
sites/openlibrary/pages/reading_list_action.py — Stepper action module for OL reading list.

Wires the exam's ReadingListPage into the ActionRegistry as ol_assert_count.
Dependency direction: sites.openlibrary → stepper  (correct)
                      sites.openlibrary → openlibrary  (correct)
"""

from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class OLReadingListPage(PageModule):
    site = "ol"

    class OLAssertCountAction(ActionStrategy):
        """
        Navigate to the reading list, count books across both shelves,
        assert the count matches expected.

        Supports:
          extra.delta          → count_before + delta
          extra.expected_count → absolute count

        JSON usage:
          { "action": "ol_assert_count", "extra": { "delta": 5 } }
        """
        action_name = "ol_assert_count"
        read_only   = True

        async def _execute(self, page, step: StepConfig,
                           resolver, context: ExecutionContext) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.auth import is_login_required, login
                from shared_poms.pages.reading_list_page import ReadingListPage

                settings     = load_settings()
                driver       = PlaywrightDriver(page)
                reading_list = ReadingListPage(
                    driver, settings.base_url, settings.delays,
                    page=page, resolver=resolver,
                )

                await reading_list.open()
                if await is_login_required(driver):
                    if settings.username and settings.password:
                        await login(driver, settings.username, settings.password)
                        await reading_list.open()

                # Wait for books to load/persist after navigation
                import asyncio
                await asyncio.sleep(2)
                actual = await reading_list.get_book_count()

                if "expected_count" in step.extra:
                    expected = int(step.extra["expected_count"])
                elif "delta" in step.extra:
                    expected = context.get_count("count_before") + int(step.extra["delta"])
                else:
                    return StepResult(step=step, status="failed",
                                      error="ol_assert_count requires extra.expected_count or extra.delta")

                if actual != expected:
                    return StepResult(step=step, status="failed",
                                      error=f"Reading list: expected {expected} books, got {actual}")

                logger.info(f"ol_assert_count ✓ — {actual} books == {expected}")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error(f"ol_assert_count failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        actions = [cls.OLAssertCountAction()]
        for action in actions:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(
                    f"{action.__class__.__name__}.action_name must start with "
                    f"'{cls.site}_', got '{action.action_name}'"
                )
            registry.register(action)
            logger.debug(f"Registered page action: {action.action_name}")
