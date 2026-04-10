# tests/test_all_flows_comprehensive.py
"""
Comprehensive flow testing with all test data combinations.
Tests every possible flow variant.
"""

import pytest
from shared_poms.config import load_test_data
from openlibrary.api import (
    search_books_by_title_under_year,
    add_books_to_reading_list,
    assert_reading_list_count,
)
from stepper.runner.api import StepperSession


TEST_DATA = load_test_data()


class TestAllFlows:
    """Test all flows with all data combinations."""
    
    @pytest.mark.parametrize("test_case", TEST_DATA)
    @pytest.mark.asyncio
    async def test_flow_search_only(self, test_case):
        """Flow 1: Search only"""
        urls = await search_books_by_title_under_year(
            query=test_case["query"],
            max_year=test_case["max_year"],
            limit=test_case["limit"],
        )
        assert len(urls) > 0
    
    
    @pytest.mark.parametrize("test_case", TEST_DATA)
    @pytest.mark.asyncio
    async def test_flow_search_and_add(self, test_case):
        """Flow 2: Search → Add"""
        urls = await search_books_by_title_under_year(
            query=test_case["query"],
            max_year=test_case["max_year"],
            limit=test_case["limit"],
        )
        await add_books_to_reading_list(urls)
    
    
    @pytest.mark.parametrize("test_case", TEST_DATA)
    @pytest.mark.asyncio
    async def test_flow_complete(self, test_case):
        """Flow 3: Search → Add → Assert (Complete Flow)"""
        urls = await search_books_by_title_under_year(
            query=test_case["query"],
            max_year=test_case["max_year"],
            limit=test_case["limit"],
        )
        await add_books_to_reading_list(urls)
        await assert_reading_list_count(expected=test_case["expected_count"])
    
    
    @pytest.mark.parametrize("test_case", TEST_DATA)
    @pytest.mark.asyncio
    async def test_flow_stepper_collect(self, test_case):
        """Flow 4: Stepper - Collect books only"""
        async with StepperSession(headless=True) as session:
            steps = [{
                "action": "ol_collect_books",
                "extra": {
                    "query": test_case["query"],
                    "filter": {"year_max": test_case["max_year"]},
                    "limit": test_case["limit"]
                }
            }]
            results, context = await session.run(steps)
            assert results[0].status == "passed"
    
    
    @pytest.mark.parametrize("test_case", TEST_DATA)
    @pytest.mark.asyncio
    async def test_flow_stepper_complete(self, test_case):
        """Flow 5: Stepper - Complete (Collect → Add → Assert)"""
        async with StepperSession(headless=True) as session:
            # Collect
            collect_steps = [{
                "action": "ol_collect_books",
                "extra": {
                    "query": test_case["query"],
                    "filter": {"year_max": test_case["max_year"]},
                    "limit": test_case["limit"]
                }
            }]
            _, context = await session.run(collect_steps)
            
            # Add
            urls = context.collected_items
            add_steps = [{
                "action": "ol_add_to_shelf",
                "extra": {"url": url, "shelf": "want-to-read"}
            } for url in urls]
            _, context = await session.run(add_steps, initial_context=context)
            
            # Assert
            assert_steps = [{
                "action": "ol_assert_count",
                "extra": {"expected_count": test_case["expected_count"]}
            }]
            results, _ = await session.run(assert_steps, initial_context=context)
            assert results[0].status == "passed"