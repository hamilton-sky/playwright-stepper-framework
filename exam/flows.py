"""
flows.py -- The 4 exact exam function signatures (OpenLibrary).

Each function orchestrates one end-to-end flow by delegating to
shared_poms POM classes. No direct Playwright calls here.

Layer position in the architecture:
    shared_poms/pages/   <- interact with a single page        (POM layer)
    exam/flows.py        <- orchestrate pages into flows       <- THIS FILE
    exam/tests/          <- call flows and assert outcomes     (test layer)

Usage:
    from flows import (
        search_books_by_title_under_year,
        add_books_to_reading_list,
        assert_reading_list_count,
        measure_page_performance,
    )
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

# Make shared_poms importable when this module is run or imported standalone
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from shared_poms.driver import PlaywrightDriver
from shared_poms.config import load_settings
from shared_poms.pages.book_search_page import BookSearchPage
from shared_poms.pages.book_detail_page import BookDetailPage
from shared_poms.pages.reading_list_page import ReadingListPage
from shared_poms.performance import measure_page_performance as _measure_perf
from shared_poms.utils.screenshot import ScreenshotManager

logger = logging.getLogger(__name__)


async def search_books_by_title_under_year(
    page, query: str, max_year: int, limit: int = 5
) -> list[str]:
    """
    Search OpenLibrary by *query*, filter results to books published
    before *max_year*, and return up to *limit* book URLs.

    Supports pagination -- moves to the next page when fewer than *limit*
    results have been collected and more pages exist.
    Returns an empty list when no matches are found.
    """
    settings = load_settings()
    driver = PlaywrightDriver(page)
    search_page = BookSearchPage(driver, settings.base_url, settings.delays)
    await search_page.search(query)
    return await search_page.collect_books_under_year(max_year, limit)


async def add_books_to_reading_list(page, urls: list[str]) -> None:
    """
    Navigate to each URL and click "Want to Read" or "Already Read" (random).
    Takes a screenshot after every book that is added.
    """
    settings = load_settings()
    driver = PlaywrightDriver(page)
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


async def assert_reading_list_count(page, expected_count: int) -> None:
    """
    Open the reading list pages, count all books across both shelves,
    and assert the total equals *expected_count*.
    """
    settings = load_settings()
    driver = PlaywrightDriver(page)
    reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
    actual = await reading_list.get_book_count()
    assert actual == expected_count, (
        f"Expected {expected_count} books on reading list, got {actual}"
    )


async def measure_page_performance(
    page, url: str, threshold_ms: int
) -> dict:
    """
    Measure first_paint_ms, dom_content_loaded_ms, and load_time_ms.
    Logs a warning when load_time exceeds *threshold_ms* (not a failure).
    Writes results to performance_report.json.
    """
    settings = load_settings()
    driver = PlaywrightDriver(page)
    return await _measure_perf(
        driver, url, threshold_ms,
        output_path=settings.performance_output,
    )
