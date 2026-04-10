# stepper/tests/test_stepper_data_driven.py
"""
Data-driven tests using testdata.json
Run each test case through stepper workflows
"""

import pytest
from pathlib import Path
from shared_poms.config import load_test_data
from stepper.runner.api import StepperSession


# Load test data once
TEST_DATA = load_test_data()


class TestStepperDataDriven:
    """Run all test cases through stepper."""
    
    @pytest.mark.parametrize("test_case", TEST_DATA, ids=lambda tc: tc.get("query"))
    @pytest.mark.asyncio
    async def test_stepper_collect_books(self, test_case):
        """
        Data-driven: Test ol_collect_books with multiple datasets.
        
        Parametrizes over testdata.json — each row becomes a test.
        """
        query = test_case["query"]
        max_year = test_case["max_year"]
        limit = test_case["limit"]
        
        print(f"\n📚 Testing: query='{query}', max_year={max_year}, limit={limit}")
        
        async with StepperSession(headless=True) as session:
            steps = [
                {
                    "action": "ol_collect_books",
                    "extra": {
                        "query": query,
                        "filter": {"year_max": max_year},
                        "limit": limit
                    }
                }
            ]
            
            results, context = await session.run(steps)
            
            # Verify step passed
            assert results[0].status == "passed", \
                f"Step failed for {query}"
            
            # Verify we got books
            urls = context.collected_items
            assert len(urls) > 0, \
                f"No books found for '{query}'"
            
            # Verify we got expected limit (or available books)
            assert len(urls) <= limit, \
                f"Got more books than limit: {len(urls)} > {limit}"
            
            print(f"  ✓ Found {len(urls)} books")
            return urls
    
    
    @pytest.mark.parametrize("test_case", TEST_DATA, ids=lambda tc: tc.get("query"))
    @pytest.mark.asyncio
    async def test_stepper_add_and_assert(self, test_case):
        """
        Data-driven: Full flow (collect → add → assert) for each test case.
        
        Tests that we can:
        1. Search and collect books
        2. Add them to reading list
        3. Assert the count matches
        """
        query = test_case["query"]
        max_year = test_case["max_year"]
        limit = test_case["limit"]
        expected_count = test_case["expected_count"]
        
        print(f"\n📚 Full Flow: '{query}' → add {limit} → assert {expected_count}")
        
        async with StepperSession(headless=True) as session:
            
            # STEP 1: Collect
            print(f"  [1] Collecting {limit} books...")
            collect_steps = [
                {
                    "action": "ol_collect_books",
                    "extra": {
                        "query": query,
                        "filter": {"year_max": max_year},
                        "limit": limit
                    }
                }
            ]
            
            results, context = await session.run(collect_steps)
            assert results[0].status == "passed"
            urls = context.collected_items
            print(f"    ✓ Collected {len(urls)} books")
            
            # STEP 2: Add to shelf
            print(f"  [2] Adding {len(urls)} to shelf...")
            add_steps = [
                {
                    "action": "ol_add_to_shelf",
                    "extra": {
                        "url": url,
                        "shelf": "want-to-read"
                    }
                }
                for url in urls
            ]
            
            results, context = await session.run(add_steps, initial_context=context)
            assert all(r.status == "passed" for r in results), \
                f"Some books failed to add for '{query}'"
            print(f"    ✓ Added {len(urls)} books")
            
            # STEP 3: Assert count
            print(f"  [3] Asserting count = {expected_count}...")
            assert_steps = [
                {
                    "action": "ol_assert_count",
                    "extra": {
                        "expected_count": expected_count
                    }
                }
            ]
            
            results, context = await session.run(assert_steps, initial_context=context)
            assert results[0].status == "passed", \
                f"Count mismatch for '{query}'"
            print(f"    ✓ Count verified!")