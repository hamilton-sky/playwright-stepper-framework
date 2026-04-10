"""
sites/openlibrary/pages/reading_list_action.py — Stepper action module for OL reading list.

Wires ReadingListPage + BookDetailPage into the ActionRegistry.
Actions registered here:
  ol_clear_reading_list — remove all books from the want-to-read shelf
  ol_store_count        — count books across both shelves, store in context
  ol_assert_count       — assert count matches expected (delta or absolute)
  ol_ensure_count       — top-up: add only the books needed to reach a target count

All CSS selectors live in the POMs. JSON workflows need only action names.

Dependency direction: sites.openlibrary → stepper  (correct)
                      sites.openlibrary → shared_poms  (correct)
"""

from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class OLReadingListPage(PageModule):
    site = "ol"

    class OLClearReadingListAction(ActionStrategy):
        """
        Remove every book from the want-to-read shelf.

        Uses ReadingListPage.collect_all_book_urls() to find books and
        BookDetailPage.remove_from_shelf() to remove each one. All CSS
        selectors (ul.list-books, button.book-progress-btn, button.remove-from-list)
        are owned by the POMs — not visible to JSON callers.

        JSON usage:
          { "action": "ol_clear_reading_list" }
        """
        action_name = "ol_clear_reading_list"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.pages.reading_list_page import ReadingListPage
                from shared_poms.pages.book_detail_page import BookDetailPage

                settings     = load_settings()
                driver       = PlaywrightDriver(page)
                reading_list = ReadingListPage(
                    driver, settings.base_url, settings.delays,
                    page=page, resolver=resolver,
                )

                urls = await reading_list.collect_all_book_urls(
                    ReadingListPage._WANT_TO_READ_PATH
                )

                if not urls:
                    logger.info("ol_clear_reading_list — shelf already empty")
                    return StepResult(step=step, status="passed")

                logger.info(f"ol_clear_reading_list — removing {len(urls)} book(s)")
                for idx, url in enumerate(urls, start=1):
                    detail = BookDetailPage(
                        driver, settings.base_url, url, settings.delays,
                        page=page, resolver=resolver,
                    )
                    await detail.open()
                    removed = await detail.remove_from_shelf()
                    logger.info(
                        f"  [{idx}/{len(urls)}] {'removed' if removed else 'not on shelf'}: {url}"
                    )

                logger.info("ol_clear_reading_list ✓")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error(f"ol_clear_reading_list failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    class OLStoreCountAction(ActionStrategy):
        """
        Count books across both shelves and store the result in context.

        Uses ReadingListPage.get_book_count() — all CSS selectors for
        ul.list-books > li and pagination live inside the POM.

        JSON usage:
          { "action": "ol_store_count", "extra": { "context_key": "count_before" } }

        context_key defaults to "count_before" when not specified.
        """
        action_name = "ol_store_count"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.pages.reading_list_page import ReadingListPage

                settings     = load_settings()
                driver       = PlaywrightDriver(page)
                reading_list = ReadingListPage(
                    driver, settings.base_url, settings.delays,
                    page=page, resolver=resolver,
                )

                context_key = step.extra.get("context_key", "count_before")
                count = await reading_list.get_book_count()
                context.set_count(context_key, count)

                logger.info(f"ol_store_count ✓ — {context_key}={count}")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error(f"ol_store_count failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

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

    class OLEnsureCountAction(ActionStrategy):
        """
        Ensure the reading list has at least `target_count` books.

        Counts current books across both shelves. If the count is already at
        or above the target, passes immediately without adding anything.
        Otherwise calculates the gap, collects exactly that many books, adds
        them, then asserts the final count equals the target.

        All selector knowledge stays in the POMs — this action never touches CSS.

        JSON usage:
          {
            "action": "ol_ensure_count",
            "extra": {
              "target_count": 5,
              "query": "Dune",
              "filter": { "year_max": 1980 }
            }
          }
        """
        action_name = "ol_ensure_count"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.pages.reading_list_page import ReadingListPage
                from sites.openlibrary.pages.search_page import OLSearchPage
                from sites.openlibrary.pages.detail_page import OLDetailPage

                settings     = load_settings()
                driver       = PlaywrightDriver(page)
                reading_list = ReadingListPage(
                    driver, settings.base_url, settings.delays,
                    page=page, resolver=resolver,
                )

                # 1. Count what is already on the shelves
                current = await reading_list.get_book_count()
                target  = int(step.extra["target_count"])

                # 2. Already at or above target — nothing to do
                if current >= target:
                    logger.info(
                        f"ol_ensure_count ✓ — already at {current}/{target}, no adds needed"
                    )
                    return StepResult(step=step, status="passed")

                # 3. Calculate how many are missing
                gap = target - current
                logger.info(
                    f"ol_ensure_count — shelf has {current}/{target}, need {gap} more"
                )

                # 4. Collect exactly `gap` books using the existing collect action
                collect_step = StepConfig(
                    action="ol_collect_books",
                    description=f"Collect {gap} books to top up to {target}",
                    extra={
                        "query":  step.extra.get("query", ""),
                        "filter": step.extra.get("filter", {}),
                        "limit":  gap,
                    },
                )
                collect_result = await OLSearchPage.OLCollectBooksAction()._execute(
                    page, collect_step, resolver, context
                )
                if collect_result.status != "passed":
                    return StepResult(step=step, status="failed",
                                      error=f"ol_ensure_count: collect step failed — {collect_result.error}")

                # 5. Add collected books to the shelf using the existing add action
                add_step = StepConfig(
                    action="ol_add_to_shelf",
                    description="Add top-up books to shelf",
                )
                add_result = await OLDetailPage.OLAddToShelfAction()._execute(
                    page, add_step, resolver, context
                )
                if add_result.status == "failed":
                    return StepResult(step=step, status="failed",
                                      error=f"ol_ensure_count: add step failed — {add_result.error}")

                # 6. Verify final count matches target
                import asyncio
                await asyncio.sleep(2)
                final = await reading_list.get_book_count()
                if final != target:
                    return StepResult(
                        step=step, status="failed",
                        error=f"ol_ensure_count: expected {target} books after top-up, got {final}",
                    )

                logger.info(f"ol_ensure_count ✓ — reading list now at {final}/{target}")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error(f"ol_ensure_count failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        actions = [
            cls.OLClearReadingListAction(),
            cls.OLStoreCountAction(),
            cls.OLAssertCountAction(),
            cls.OLEnsureCountAction(),
        ]
        for action in actions:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(
                    f"{action.__class__.__name__}.action_name must start with "
                    f"'{cls.site}_', got '{action.action_name}'"
                )
            registry.register(action)
            logger.debug(f"Registered page action: {action.action_name}")
