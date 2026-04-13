"""
tests/test_openlibrary_exam.py -- Pytest test class for the OpenLibrary exam.

This file contains ONLY test logic -- no browser setup, no navigation code.
All flow logic lives in exam/flows.py.

Run:
    cd exam/
    pytest tests/ -v
    pytest tests/ -v --headed
    pytest tests/ -v --alluredir=reports/allure-results
"""
from __future__ import annotations

import logging

import allure
import pytest

from poms.openLibrary.config import load_settings
from poms.openLibrary.pages.reading_list_page import ReadingListPage
from flows import (
    search_books_by_title_under_year,
    add_books_to_reading_list,
    assert_reading_list_count,
    measure_page_performance,
)
from conftest import requires_auth

logger = logging.getLogger(__name__)

BASE_URL = load_settings().base_url


@allure.epic("OpenLibrary Exam")
@allure.feature("Book Search & Reading List")
class TestOpenLibraryExam:
    """
    End-to-end: search -> add -> assert -> measure performance.

    Mirrors the exam's main() flow:
        urls = search_books_by_title_under_year(driver, settings, "Dune", 1980, 5)
        add_books_to_reading_list(driver, settings, urls)
        assert_reading_list_count(driver, settings, len(urls))
    """

    @allure.story("Search books by title under year")
    @pytest.mark.asyncio
    async def test_search_books(self, driver, settings, test_case, result_key, _shared_results):
        urls = await search_books_by_title_under_year(
            driver, settings, test_case["query"], test_case["max_year"], test_case["limit"]
        )
        assert isinstance(urls, list)
        assert len(urls) <= test_case["limit"]
        for url in urls:
            assert url.startswith("http")
        _shared_results[result_key] = {"urls": urls}

    @allure.story("Add books to reading list")
    @requires_auth
    @pytest.mark.asyncio
    async def test_add_books(self, driver, settings, result_key, _shared_results):
        urls = _shared_results.get(result_key, {}).get("urls", [])
        assert urls, "No URLs collected -- run test_search_books first"
        # Record count before so assert test can compute a valid delta.
        reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
        _shared_results[result_key]["count_before"] = await reading_list.get_book_count()
        await add_books_to_reading_list(driver, settings, urls)
        # Capture count immediately after adding, before other cases run.
        _shared_results[result_key]["count_after"] = await reading_list.get_book_count()

    @allure.story("Assert reading list count")
    @requires_auth
    @pytest.mark.asyncio
    async def test_assert_reading_list_count(self, driver, settings, result_key, _shared_results):
        urls = _shared_results.get(result_key, {}).get("urls", [])
        assert urls, "No URLs collected -- run test_search_books first"
        count_before = _shared_results.get(result_key, {}).get("count_before", 0)
        # Use count captured right after adding (before other cases ran).
        count_after = _shared_results.get(result_key, {}).get("count_after")
        assert count_after is not None, "count_after not captured -- run test_add_books first"

        newly_added = count_after - count_before
        assert 0 <= newly_added <= len(urls), (
            f"Expected 0-{len(urls)} new books added, "
            f"but count changed by {newly_added} (before={count_before}, after={count_after})"
        )
        # Assert the live count matches count_after (captured right after adding).
        # count_after already accounts for books that were already shelved (idempotent adds).
        # This catches real failures: books disappearing between the two tests.
        await assert_reading_list_count(driver, settings, count_after)

    @allure.story("Measure page performance -- search page")
    @pytest.mark.asyncio
    async def test_measure_performance_search(self, driver, settings):
        result = await measure_page_performance(
            driver, settings, f"{BASE_URL}/search?q=Dune", threshold_ms=3000,
        )
        assert "metrics" in result
        assert "load_time_ms" in result["metrics"]

    @allure.story("Measure page performance -- book detail")
    @pytest.mark.asyncio
    async def test_measure_performance_detail(self, driver, settings):
        # A known stable Dune edition detail page
        result = await measure_page_performance(
            driver, settings, f"{BASE_URL}/works/OL18020194W/Dune", threshold_ms=2500,
        )
        assert "metrics" in result

    @allure.story("Measure page performance -- reading list")
    @pytest.mark.asyncio
    async def test_measure_performance_reading_list(self, driver, settings):
        result = await measure_page_performance(
            driver, settings, f"{BASE_URL}/account/books/want-to-read", threshold_ms=2000,
        )
        assert "metrics" in result
