import json

import allure
import pytest
from allure_commons.types import AttachmentType
from playwright.async_api import async_playwright

from shared_poms.config import load_settings, load_test_data
from openlibrary.api import measure_page_performance
from openlibrary.orchestrator import FlowOrchestrator


@allure.feature("OpenLibrary")
@allure.story("Search -> Add -> Assert")
@pytest.mark.asyncio
async def test_search_add_and_assert(orch: FlowOrchestrator, reading_list_count_before: int):
    """
    Integration test: search → add → assert, one orchestrator call per step.

    Each allure.step maps to exactly one operation so failures are immediately
    pinpointed to the phase that broke — search, add, or assert.
    """
    cases        = load_test_data()
    running_count = reading_list_count_before

    for case in cases:
        expected = running_count + case["limit"]

        with allure.step(f"Search '{case['query']}' max_year={case['max_year']} limit={case['limit']}"):
            urls = await orch.search(case["query"], case["max_year"], case["limit"])
            assert len(urls) == case["limit"], (
                f"Expected {case['limit']} URLs, got {len(urls)}"
            )
            allure.attach(
                json.dumps(urls, indent=2),
                name=f"urls_{case['query']}",
                attachment_type=AttachmentType.JSON,
            )

        with allure.step(f"Add {len(urls)} books to reading list"):
            await orch.add_books(urls)

        with allure.step(f"Assert reading list count == {expected}"):
            await orch.assert_count(expected)

        running_count = expected


@allure.feature("OpenLibrary")
@allure.story("Performance")
@pytest.mark.asyncio
async def test_performance_measurement():
    """
    Measure load performance for all three exam-required pages.
    Thresholds per exam spec:
      Search page     3000ms
      Add/Detail page 2500ms
      Reading List    2000ms
    """
    settings = load_settings()
    base     = settings.base_url.rstrip("/")

    pages_to_measure = [
        (f"{base}/search",                     3000, "search_page"),
        (f"{base}/works/OL82563W",             2500, "add_detail_page"),
        (f"{base}/account/books/want-to-read", 2000, "reading_list_page"),
    ]

    async with async_playwright() as p:
        browser = await getattr(p, settings.browser).launch(headless=settings.headless)
        page    = await browser.new_page()

        all_reports = {}
        for url, threshold, label in pages_to_measure:
            with allure.step(f"Measure {label} (threshold {threshold}ms)"):
                report = await measure_page_performance(page, url, threshold)
                all_reports[label] = report
                allure.attach(
                    json.dumps(report, indent=2),
                    name=f"performance_{label}",
                    attachment_type=AttachmentType.JSON,
                )

        await browser.close()

    from pathlib import Path
    combined_path = Path(settings.performance_output)
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_text(json.dumps(all_reports, indent=2), encoding="utf-8")
    allure.attach(
        json.dumps(all_reports, indent=2),
        name="performance_report_combined",
        attachment_type=AttachmentType.JSON,
    )

    for label, report in all_reports.items():
        assert report.get("metrics"), f"No performance metrics collected for {label}"
