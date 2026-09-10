"""
PaginateAction — the loop bounds, both navigation styles, and the stop conditions.

This action drives ExtractDataAction in a while-loop across pages. Its caps are
the only thing standing between a workflow and an unbounded crawl, and its
`limit` arithmetic (shrinking as items accumulate) is easy to get subtly wrong.

No browser — the page and the extract action are stubs.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.actions.strategies import PaginateAction
from engine.interfaces import ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult


# ── Doubles ───────────────────────────────────────────────────────────────────

class FakeExtract(ActionStrategy):
    """
    Stands in for extract_data: yields a canned batch per call and records the
    limit it was handed, which is how paginate communicates its remaining budget.
    """

    action_name = "extract_data"
    read_only = True

    def __init__(self, batches):
        self._batches = list(batches)
        self.limits: list = []
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        limit = step.extra.get("limit")
        self.limits.append(limit)
        batch = self._batches[self.calls] if self.calls < len(self._batches) else []
        self.calls += 1
        # The real ExtractDataAction slices to `limit`; a fake that ignores it
        # would let paginate appear to overshoot max_items when it does not.
        context.extracted_data = list(batch)[:limit] if limit is not None else list(batch)
        return StepResult(step=step, status="passed")


class FailingExtract(ActionStrategy):
    action_name = "extract_data"
    read_only = True

    async def _execute(self, page, step, resolver, context, behaviour=None):
        context.extracted_data = []
        return StepResult(step=step, status="failed", error="selector missing")


class FakeFactory(ActionFactory):
    def __init__(self, action):
        self._action = action

    def create(self, action_name):
        assert action_name == "extract_data"
        return self._action


@pytest.fixture
def page():
    p = MagicMock()
    p.url = "https://openlibrary.org/search/page1"
    p.goto = AsyncMock()
    p.wait_for_load_state = AsyncMock()
    return p


def next_button(enabled=True, visible=True):
    btn = MagicMock()
    btn.is_enabled = AsyncMock(return_value=enabled)
    btn.is_visible = AsyncMock(return_value=visible)
    btn.click = AsyncMock()
    return btn


def paginate(page, extract_action, **extra):
    extra.setdefault("extract_config", {"selector": ".result"})
    step = StepConfig(action="paginate", description="paginate", extra=extra)
    ctx = ExecutionContext()
    action = PaginateAction(FakeFactory(extract_action))
    result = asyncio.run(action.execute(page, step, MagicMock(), ctx))
    return result, ctx


# ── Required input ────────────────────────────────────────────────────────────

def test_a_missing_extract_selector_fails(page):
    step = StepConfig(action="paginate", description="p", extra={"extract_config": {}})
    action = PaginateAction(FakeFactory(FakeExtract([])))

    result = asyncio.run(action.execute(page, step, MagicMock(), ExecutionContext()))

    assert result.status == "failed"
    assert "extract_config.selector" in result.error


def test_neither_navigation_style_fails(page):
    result, _ = paginate(page, FakeExtract([["a"]]))

    assert result.status == "failed"
    assert "next_button_selector or next_url_pattern" in result.error


# ── URL-based pagination ──────────────────────────────────────────────────────

def test_url_pagination_accumulates_across_pages(page):
    extract = FakeExtract([["a", "b"], ["c"], []])

    result, ctx = paginate(page, extract,
                           next_url_pattern="/search?page={{page_num}}",
                           max_pages=3)

    assert result.status == "passed"
    assert ctx.paginated_data == ["a", "b", "c"]


def test_url_pagination_substitutes_the_page_number(page):
    extract = FakeExtract([["a"], ["b"], []])

    paginate(page, extract, next_url_pattern="/search?page={{page_num}}", max_pages=3)

    visited = [c.args[0] for c in page.goto.await_args_list]
    assert visited[0].endswith("/search?page=2")
    assert visited[1].endswith("/search?page=3")


def test_an_absolute_next_url_is_used_as_given(page):
    extract = FakeExtract([["a"], []])

    paginate(page, extract,
             next_url_pattern="https://elsewhere.test/p{{page_num}}", max_pages=2)

    assert page.goto.await_args_list[0].args[0] == "https://elsewhere.test/p2"


def test_pagination_stops_when_navigation_fails(page):
    page.goto = AsyncMock(side_effect=RuntimeError("404"))
    extract = FakeExtract([["a"], ["b"]])

    result, ctx = paginate(page, extract,
                           next_url_pattern="/p{{page_num}}", max_pages=5)

    assert result.status == "passed"
    assert ctx.paginated_data == ["a"]     # only the first page was read
    assert extract.calls == 1


# ── Button-based pagination ───────────────────────────────────────────────────

def test_button_pagination_clicks_through(page):
    page.locator = MagicMock(return_value=next_button())
    extract = FakeExtract([["a"], ["b"], []])

    result, ctx = paginate(page, extract, next_button_selector=".next", max_pages=3)

    assert result.status == "passed"
    assert ctx.paginated_data == ["a", "b"]


@pytest.mark.parametrize("enabled,visible", [(False, True), (True, False), (False, False)])
def test_pagination_stops_when_the_next_button_is_not_clickable(enabled, visible, page):
    page.locator = MagicMock(return_value=next_button(enabled=enabled, visible=visible))
    extract = FakeExtract([["a"], ["b"]])

    result, ctx = paginate(page, extract, next_button_selector=".next", max_pages=5)

    assert result.status == "passed"
    assert ctx.paginated_data == ["a"]
    assert extract.calls == 1


def test_pagination_stops_when_the_button_lookup_raises(page):
    page.locator = MagicMock(side_effect=RuntimeError("detached"))
    extract = FakeExtract([["a"], ["b"]])

    _, ctx = paginate(page, extract, next_button_selector=".next", max_pages=5)

    assert ctx.paginated_data == ["a"]


# ── Caps ──────────────────────────────────────────────────────────────────────

def test_max_pages_bounds_the_loop(page):
    extract = FakeExtract([["a"], ["b"], ["c"], ["d"], ["e"]])

    _, ctx = paginate(page, extract, next_url_pattern="/p{{page_num}}", max_pages=2)

    assert extract.calls == 2
    assert ctx.paginated_data == ["a", "b"]


def test_max_items_bounds_the_total(page):
    extract = FakeExtract([["a", "b"], ["c", "d"], ["e", "f"]])

    _, ctx = paginate(page, extract, next_url_pattern="/p{{page_num}}",
                      max_pages=10, max_items=3)

    assert ctx.paginated_data == ["a", "b", "c"]   # exactly the budget
    assert extract.calls == 2                      # stopped once it was met


def test_the_extract_limit_shrinks_as_items_accumulate(page):
    """Each page is only allowed to fetch the remaining budget."""
    extract = FakeExtract([["a", "b"], ["c"], []])

    paginate(page, extract, next_url_pattern="/p{{page_num}}",
             max_pages=3, max_items=5)

    assert extract.limits[0] == 5      # nothing collected yet
    assert extract.limits[1] == 3      # two already collected


def test_an_explicit_extract_limit_is_respected_when_smaller(page):
    extract = FakeExtract([["a"], []])

    paginate(page, extract,
             extract_config={"selector": ".r", "limit": 2},
             next_url_pattern="/p{{page_num}}", max_pages=2, max_items=100)

    assert extract.limits[0] == 2


# ── Extraction failures ───────────────────────────────────────────────────────

def test_a_failing_extract_yields_no_items_but_still_passes(page):
    """paginate reports its own success; an empty crawl is not an error."""
    result, ctx = paginate(page, FailingExtract(),
                           next_url_pattern="/p{{page_num}}", max_pages=2)

    assert result.status == "passed"
    assert ctx.paginated_data == []


def test_results_land_in_paginated_data(page):
    extract = FakeExtract([["a"], []])

    _, ctx = paginate(page, extract, next_url_pattern="/p{{page_num}}", max_pages=2)

    assert ctx.paginated_data == ["a"]
    assert ctx.extracted_data == []     # the last page's batch was empty
