"""
Characterization tests for evaluate_when — the `when:` condition evaluator.

Every condition type documented in when_eval.py's module docstring is covered,
plus the two behaviours workflow authors are most likely to trip over:

  - context_key_exists is *truthiness*, not presence: 0, [] and "" all skip.
  - an unrecognised condition fails OPEN (the step runs), while a broken
    element_exists selector fails CLOSED (the step is skipped).

No browser: page is a stub.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.interfaces import ExecutionContext
from engine.runner.when_eval import evaluate_when


@pytest.fixture
def ctx():
    c = ExecutionContext()
    c.set_count("count", 5)
    c.set_count("zero", 0)
    c.collected_items = ["a", "b"]
    return c


@pytest.fixture
def page():
    p = MagicMock()
    p.url = "https://openlibrary.org/account/login"
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    p.locator.return_value = loc
    return p


def _with_elements(page, n):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=n)
    page.locator.return_value = loc
    return page


# ── Empty / missing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("condition", [None, {}])
async def test_empty_condition_runs_the_step(condition, ctx, page):
    assert await evaluate_when(condition, ctx, page) is True


# ── context_equals ────────────────────────────────────────────────────────────

async def test_context_equals_matches(ctx, page):
    assert await evaluate_when({"context_equals": {"key": "count", "value": 5}}, ctx, page)


async def test_context_equals_mismatches(ctx, page):
    assert not await evaluate_when({"context_equals": {"key": "count", "value": 9}}, ctx, page)


async def test_context_equals_on_missing_key_is_false(ctx, page):
    assert not await evaluate_when({"context_equals": {"key": "nope", "value": 1}}, ctx, page)


async def test_context_equals_missing_key_matches_none(ctx, page):
    """A key that was never set reads as None, so value: null matches it."""
    assert await evaluate_when({"context_equals": {"key": "nope", "value": None}}, ctx, page)


# ── context_key_exists ────────────────────────────────────────────────────────

async def test_context_key_exists_true_for_non_empty(ctx, page):
    assert await evaluate_when({"context_key_exists": "collected_items"}, ctx, page)


async def test_context_key_exists_false_for_missing(ctx, page):
    assert not await evaluate_when({"context_key_exists": "nope"}, ctx, page)


async def test_context_key_exists_is_truthiness_not_presence(ctx, page):
    """A key set to 0 is present but falsy — the step is skipped."""
    assert not await evaluate_when({"context_key_exists": "zero"}, ctx, page)


async def test_context_key_exists_false_for_empty_list(ctx, page):
    ctx.collected_items = []
    assert not await evaluate_when({"context_key_exists": "collected_items"}, ctx, page)


# ── Numeric comparisons ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [(4, True), (5, False), (6, False)])
async def test_context_greater_than(value, expected, ctx, page):
    got = await evaluate_when({"context_greater_than": {"key": "count", "value": value}}, ctx, page)
    assert got is expected


@pytest.mark.parametrize("value,expected", [(6, True), (5, False), (4, False)])
async def test_context_less_than(value, expected, ctx, page):
    got = await evaluate_when({"context_less_than": {"key": "count", "value": value}}, ctx, page)
    assert got is expected


async def test_comparisons_treat_a_missing_key_as_zero(ctx, page):
    assert await evaluate_when({"context_less_than": {"key": "nope", "value": 1}}, ctx, page)
    assert not await evaluate_when({"context_greater_than": {"key": "nope", "value": 0}}, ctx, page)


@pytest.mark.parametrize("lo,hi,expected", [(2, 8, True), (5, 5, True), (6, 8, False), (1, 4, False)])
async def test_context_between_is_inclusive(lo, hi, expected, ctx, page):
    got = await evaluate_when({"context_between": {"key": "count", "min": lo, "max": hi}}, ctx, page)
    assert got is expected


# ── Page conditions ───────────────────────────────────────────────────────────

async def test_url_contains_matches_a_fragment(ctx, page):
    assert await evaluate_when({"url_contains": "/account/login"}, ctx, page)


async def test_url_contains_missing_fragment_is_false(ctx, page):
    assert not await evaluate_when({"url_contains": "/checkout"}, ctx, page)


async def test_element_exists_true_when_the_selector_matches(ctx, page):
    assert await evaluate_when({"element_exists": "input"}, ctx, _with_elements(page, 2))


async def test_element_exists_false_when_nothing_matches(ctx, page):
    assert not await evaluate_when({"element_exists": "input"}, ctx, _with_elements(page, 0))


async def test_element_exists_fails_closed_on_error(ctx, page):
    """Unlike an unknown condition, a broken selector skips the step."""
    page.locator.side_effect = RuntimeError("detached frame")
    assert not await evaluate_when({"element_exists": "#gone"}, ctx, page)


# ── Combinators ───────────────────────────────────────────────────────────────

async def test_not_inverts(ctx, page):
    assert not await evaluate_when({"not": {"url_contains": "/account/login"}}, ctx, page)
    assert await evaluate_when({"not": {"url_contains": "/checkout"}}, ctx, page)


async def test_all_requires_every_condition(ctx, page):
    assert await evaluate_when(
        {"all": [{"url_contains": "/account"}, {"context_greater_than": {"key": "count", "value": 1}}]},
        ctx, page)
    assert not await evaluate_when(
        {"all": [{"url_contains": "/account"}, {"url_contains": "/checkout"}]},
        ctx, page)


async def test_any_requires_one_condition(ctx, page):
    assert await evaluate_when(
        {"any": [{"url_contains": "/checkout"}, {"url_contains": "/account"}]}, ctx, page)
    assert not await evaluate_when(
        {"any": [{"url_contains": "/checkout"}, {"url_contains": "/cart"}]}, ctx, page)


async def test_empty_all_is_true_and_empty_any_is_false(ctx, page):
    assert await evaluate_when({"all": []}, ctx, page)
    assert not await evaluate_when({"any": []}, ctx, page)


async def test_combinators_nest(ctx, page):
    condition = {"all": [
        {"not": {"url_contains": "/checkout"}},
        {"any": [
            {"context_equals": {"key": "count", "value": 99}},
            {"context_between": {"key": "count", "min": 1, "max": 10}},
        ]},
    ]}
    assert await evaluate_when(condition, ctx, page)


# ── Unknown conditions ────────────────────────────────────────────────────────

async def test_unknown_condition_fails_open(ctx, page):
    """A typo'd condition key runs the step rather than silently skipping it."""
    assert await evaluate_when({"contxt_equals": {"key": "count", "value": 5}}, ctx, page)


async def test_first_recognised_key_wins(ctx, page):
    """
    Conditions are checked in a fixed order, not merged — a dict carrying two
    condition keys is decided by whichever the evaluator tests first.
    """
    condition = {"context_equals": {"key": "count", "value": 5}, "url_contains": "/nowhere"}
    assert await evaluate_when(condition, ctx, page)
