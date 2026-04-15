"""
flows.py -- The 4 exact exam function signatures (OpenLibrary).

Each function orchestrates one end-to-end flow by delegating to
openLibrary POM classes. No direct Playwright calls here.

Layer position in the architecture:
    openLibrary/pages/   <- interact with a single page        (POM layer)
    exam/flows.py        <- orchestrate pages into flows       <- THIS FILE
    exam/tests/          <- call flows and assert outcomes     (test layer)

Public API — exam-spec signatures (accept a Playwright ``page`` object):
    search_books_by_title_under_year(page, query, max_year, limit=5) -> list[str]
    add_books_to_reading_list(page, urls)                             -> None
    assert_reading_list_count(page, expected_count)                   -> None
    measure_page_performance(page, url, threshold_ms)                 -> dict

Internal helpers (driver + settings already resolved) are prefixed ``_impl_``.
"""
from __future__ import annotations

import logging
import re

from poms.shared.interfaces import IBrowserDriver
from poms.shared.driver import PlaywrightDriver
from poms.openLibrary.config import Settings, load_settings
from poms.openLibrary.pages.book_search_page import BookSearchPage
from poms.openLibrary.pages.book_detail_page import BookDetailPage
from poms.openLibrary.pages.reading_list_page import ReadingListPage
from poms.shared.performance import measure_page_performance as _measure_perf
from poms.openLibrary.utils.screenshot import ScreenshotManager

logger = logging.getLogger(__name__)


# ─── Implementation helpers (driver + settings injected externally) ───────────

async def _impl_search_books(
    driver: IBrowserDriver, settings: Settings,
    query: str, max_year: int, limit: int = 5,
) -> list[str]:
    search_page = BookSearchPage(driver, settings.base_url, settings.delays)
    await search_page.search(query)
    results = await search_page.collect_books_under_year(max_year, limit)
    return [item["url"] for item in results]


async def _impl_add_books(
    driver: IBrowserDriver, settings: Settings, urls: list[str],
) -> None:
    screenshots_dir = settings.screenshots_dir
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_mgr = ScreenshotManager(driver, screenshots_dir)

    for idx, url in enumerate(urls, start=1):
        detail = BookDetailPage(
            driver, settings.base_url, book_url=url, delays=settings.delays,
        )
        await detail.open()
        chosen_shelf = await detail.add_to_reading_list()  # random shelf (exam spec)
        slug = re.sub(r"[^\w\-]", "_", url.split("/")[-1])[:60]
        try:
            await screenshot_mgr.capture(f"book_{idx}_{slug}")
        except Exception as e:
            logger.warning("Screenshot failed for book %d (%s): %s", idx, url, e)
        logger.info("Added book %d/%d [shelf: %s]: %s", idx, len(urls), chosen_shelf or "unknown", url)


async def _impl_assert_count(
    driver: IBrowserDriver, settings: Settings, expected_count: int,
) -> None:
    reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
    actual = await reading_list.get_book_count()
    # >= rather than == : other parametrized cases may have added books in the
    # same session. The goal is to detect books *disappearing*, not enforce an
    # exact global total. Each test captures count_before / count_after to
    # verify its own delta precisely (see test_assert_reading_list_count).
    assert actual >= expected_count, (
        f"Expected at least {expected_count} books on reading list, got {actual}"
    )


async def _impl_clear_reading_list(
    driver: IBrowserDriver, settings: Settings,
) -> None:
    """
    Remove every book from both shelves (want-to-read + already-read).
    Mirrors the Stepper's ol_clear_reading_list action.
    When this runs before adding, assert_reading_list_count can use == instead of >=.
    """
    reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
    want_urls    = await reading_list.collect_all_book_urls(ReadingListPage._WANT_TO_READ_PATH)
    already_urls = await reading_list.collect_all_book_urls(ReadingListPage._ALREADY_READ_PATH)
    urls = want_urls + already_urls

    if not urls:
        logger.info("clear_reading_list — shelf already empty")
        return

    logger.info("clear_reading_list — removing %d book(s)", len(urls))
    for idx, url in enumerate(urls, start=1):
        detail = BookDetailPage(driver, settings.base_url, book_url=url, delays=settings.delays)
        await detail.open()
        removed = await detail.remove_from_shelf()
        logger.info("  [%d/%d] %s: %s", idx, len(urls), "removed" if removed else "not on shelf", url)
    logger.info("clear_reading_list — done")


async def _impl_measure_perf(
    driver: IBrowserDriver, settings: Settings, url: str, threshold_ms: int,
) -> dict:
    return await _measure_perf(
        driver, url, threshold_ms,
        output_path=settings.performance_output,
    )


# ─── Exam-spec public API ─────────────────────────────────────────────────────
# Signatures match the exam specification exactly.
# Each wrapper accepts a Playwright ``page`` object, builds the driver and
# settings internally, then delegates to the corresponding ``_impl_*`` helper.

async def search_books_by_title_under_year(
    page, query: str, max_year: int, limit: int = 5,
) -> list[str]:
    """
    Search OpenLibrary by *query*, filter results to books published
    before *max_year*, and return up to *limit* book URLs.

    Supports pagination -- moves to the next page when fewer than *limit*
    results have been collected and more pages exist.
    Returns an empty list when no matches are found.
    """
    return await _impl_search_books(PlaywrightDriver(page), load_settings(), query, max_year, limit)


async def add_books_to_reading_list(page, urls: list[str]) -> None:
    """
    Navigate to each URL and click "Want to Read" or "Already Read" (random).
    Takes a screenshot after every book that is added.
    """
    await _impl_add_books(PlaywrightDriver(page), load_settings(), urls)


async def assert_reading_list_count(page, expected_count: int) -> None:
    """
    Open the reading list pages, count all books across both shelves,
    and assert the total is at least *expected_count*.
    """
    await _impl_assert_count(PlaywrightDriver(page), load_settings(), expected_count)


async def measure_page_performance(page, url: str, threshold_ms: int) -> dict:
    """
    Measure first_paint_ms, dom_content_loaded_ms, and load_time_ms.
    Logs a warning when load_time exceeds *threshold_ms* (not a failure).
    Writes results to performance_report.json.
    """
    return await _impl_measure_perf(PlaywrightDriver(page), load_settings(), url, threshold_ms)


async def clear_reading_list(page) -> None:
    """
    Remove all books from both reading shelves before a test run.

    Use this with --clear-before-run so that assert_reading_list_count
    can assert == (exact match) instead of >= (at-least).

    Pytest equivalent of the Stepper's ol_clear_reading_list action +
    when: context_key_exists guard pattern.
    """
    await _impl_clear_reading_list(PlaywrightDriver(page), load_settings())
