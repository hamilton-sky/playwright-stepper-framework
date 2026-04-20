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
                      sites.openlibrary → openLibrary  (correct)
"""

from __future__ import annotations
import logging


from engine.browser.human_behaviour import HumanBehaviour
from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class OLReadingListPage(PageModule):
    site = "ol"

    class OLClearReadingListAction(GlueAction):
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
            behaviour: HumanBehaviour
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.reading_list_page import ReadingListPage
                from poms.openLibrary.pages.book_detail_page import BookDetailPage

                settings     = load_settings()
                driver       = self._driver(page)
                reading_list = self._build_pom(ReadingListPage, driver, settings.base_url,
                                               settings.delays, page=page, resolver=resolver, behaviour=behaviour)

                want_urls    = await reading_list.collect_all_book_urls(ReadingListPage._WANT_TO_READ_PATH)
                already_urls = await reading_list.collect_all_book_urls(ReadingListPage._ALREADY_READ_PATH)
                urls = want_urls + already_urls

                if not urls:
                    logger.info("ol_clear_reading_list — shelf already empty")
                    return StepResult(step=step, status="passed", output={"removed": 0})

                logger.info(f"ol_clear_reading_list — removing {len(urls)} book(s)")
                for idx, url in enumerate(urls, start=1):
                    detail = self._build_pom(BookDetailPage, driver, settings.base_url,
                                            url, settings.delays, page=page, resolver=resolver, behaviour=behaviour)
                    await detail.open()
                    removed = await detail.remove_from_shelf()
                    logger.info(
                        f"  [{idx}/{len(urls)}] {'removed' if removed else 'not on shelf'}: {url}"
                    )

                logger.info("ol_clear_reading_list ✓")
                return StepResult(step=step, status="passed", output={"removed": len(urls)})

            except Exception as e:
                logger.error(f"ol_clear_reading_list failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    class OLStoreCountAction(GlueAction):
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
            behaviour: HumanBehaviour
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.reading_list_page import ReadingListPage

                settings     = load_settings()
                driver       = self._driver(page)
                reading_list = self._build_pom(ReadingListPage, driver, settings.base_url,
                                               settings.delays, page=page, resolver=resolver, behaviour=behaviour)

                context_key = step.extra.get("context_key", "count_before")
                count = await reading_list.get_book_count()
                context.set_count(context_key, count)

                logger.info(f"ol_store_count ✓ — {context_key}={count}")
                return StepResult(step=step, status="passed", output={context_key: count})

            except Exception as e:
                logger.error(f"ol_store_count failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    class OLAssertCountAction(GlueAction):
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
                           resolver, context: ExecutionContext, behaviour: HumanBehaviour) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.reading_list_page import ReadingListPage

                settings     = load_settings()
                driver       = self._driver(page)
                reading_list = self._build_pom(ReadingListPage, driver, settings.base_url,
                                               settings.delays, page=page, resolver=resolver, behaviour=behaviour)

                await reading_list.open()

                import asyncio
                await asyncio.sleep(settings.delays.page_load_wait_ms / 1000)
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
                return StepResult(step=step, status="passed", output={"actual": actual, "expected": expected})

            except Exception as e:
                logger.error(f"ol_assert_count failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    class OLEnsureCountAction(GlueAction):
        """
        Check the shelf count and store the gap in context if top-up is needed.

        Single responsibility: decide whether top-up is needed and by how much.
        The flow JSON controls what happens next — collect, add, assert are
        separate steps guarded by `when: context_key_exists: gap`.

        If already at or above target → passes immediately, gap NOT stored
        (downstream when-guards skip collect / add / assert automatically).

        If below target → stores gap in context.counts["gap"] and passes.
        The flow then runs ol_collect_books (reads gap as limit), ol_add_to_shelf,
        and ol_assert_count.

        JSON usage:
          { "action": "ol_ensure_count", "extra": { "target_count": 5 } }
        """
        action_name = "ol_ensure_count"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
            behaviour: HumanBehaviour
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.reading_list_page import ReadingListPage

                settings     = load_settings()
                driver       = self._driver(page)
                reading_list = self._build_pom(ReadingListPage, driver, settings.base_url,
                                               settings.delays, page=page, resolver=resolver, behaviour=behaviour)

                current = await reading_list.get_book_count()
                target  = int(step.extra["target_count"])

                if current >= target:
                    logger.info(
                        "ol_ensure_count ✓ — already at %d/%d, skipping top-up",
                        current, target,
                    )
                    return StepResult(step=step, status="passed",
                                      output={"current": current, "target": target, "gap": 0})

                gap = target - current
                context.set_count("gap", gap)
                logger.info(
                    "ol_ensure_count — shelf has %d/%d, gap=%d stored in context",
                    current, target, gap,
                )
                return StepResult(step=step, status="passed",
                                  output={"current": current, "target": target, "gap": gap})

            except Exception as e:
                logger.error("ol_ensure_count failed: %s", e)
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
