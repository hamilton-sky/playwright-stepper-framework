"""
Characterization tests for evaluate_when — the `when:` condition evaluator.

Every condition type documented in when_eval.py's module docstring is covered,
plus the two behaviours workflow authors are most likely to trip over:

  - context_key_exists is *truthiness*, not presence: 0, [] and "" all skip.
  - a broken element_exists selector fails CLOSED (the step is skipped), while
    an unrecognised condition now RAISES — it used to fail open and run the
    step it was meant to guard. See docs/universal-runner-plan.md, ticket T4.

Conditions are a per-domain registry now. Most of this file runs against the
web domain's vocabulary, because url_contains and element_exists are the only
ones that look at a session and they belong to it; the last section checks the
core registry has them and the combinators properly separated.

No browser: page is a stub.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.browser.conditions import web_conditions
from stepper.engine.interfaces import ExecutionContext
from stepper.engine.runner.when_eval import (
    UnknownConditionError, core_conditions, evaluate_when,
)


async def _web_eval(condition, context, page=None):
    """evaluate_when as the web domain sees it — core plus the two page ones."""
    return await evaluate_when(condition, context, page, conditions=web_conditions())


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
    assert await _web_eval(condition, ctx, page) is True


# ── context_equals ────────────────────────────────────────────────────────────

async def test_context_equals_matches(ctx, page):
    assert await _web_eval({"context_equals": {"key": "count", "value": 5}}, ctx, page)


async def test_context_equals_mismatches(ctx, page):
    assert not await _web_eval({"context_equals": {"key": "count", "value": 9}}, ctx, page)


async def test_context_equals_on_missing_key_is_false(ctx, page):
    assert not await _web_eval({"context_equals": {"key": "nope", "value": 1}}, ctx, page)


async def test_context_equals_missing_key_matches_none(ctx, page):
    """A key that was never set reads as None, so value: null matches it."""
    assert await _web_eval({"context_equals": {"key": "nope", "value": None}}, ctx, page)


# ── context_key_exists ────────────────────────────────────────────────────────

async def test_context_key_exists_true_for_non_empty(ctx, page):
    assert await _web_eval({"context_key_exists": "collected_items"}, ctx, page)


async def test_context_key_exists_false_for_missing(ctx, page):
    assert not await _web_eval({"context_key_exists": "nope"}, ctx, page)


async def test_context_key_exists_is_truthiness_not_presence(ctx, page):
    """A key set to 0 is present but falsy — the step is skipped."""
    assert not await _web_eval({"context_key_exists": "zero"}, ctx, page)


async def test_context_key_exists_false_for_empty_list(ctx, page):
    ctx.collected_items = []
    assert not await _web_eval({"context_key_exists": "collected_items"}, ctx, page)


# ── Numeric comparisons ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [(4, True), (5, False), (6, False)])
async def test_context_greater_than(value, expected, ctx, page):
    got = await _web_eval({"context_greater_than": {"key": "count", "value": value}}, ctx, page)
    assert got is expected


@pytest.mark.parametrize("value,expected", [(6, True), (5, False), (4, False)])
async def test_context_less_than(value, expected, ctx, page):
    got = await _web_eval({"context_less_than": {"key": "count", "value": value}}, ctx, page)
    assert got is expected


async def test_comparisons_treat_a_missing_key_as_zero(ctx, page):
    assert await _web_eval({"context_less_than": {"key": "nope", "value": 1}}, ctx, page)
    assert not await _web_eval({"context_greater_than": {"key": "nope", "value": 0}}, ctx, page)


@pytest.mark.parametrize("lo,hi,expected", [(2, 8, True), (5, 5, True), (6, 8, False), (1, 4, False)])
async def test_context_between_is_inclusive(lo, hi, expected, ctx, page):
    got = await _web_eval({"context_between": {"key": "count", "min": lo, "max": hi}}, ctx, page)
    assert got is expected


# ── Page conditions ───────────────────────────────────────────────────────────

async def test_url_contains_matches_a_fragment(ctx, page):
    assert await _web_eval({"url_contains": "/account/login"}, ctx, page)


async def test_url_contains_missing_fragment_is_false(ctx, page):
    assert not await _web_eval({"url_contains": "/checkout"}, ctx, page)


async def test_element_exists_true_when_the_selector_matches(ctx, page):
    assert await _web_eval({"element_exists": "input"}, ctx, _with_elements(page, 2))


async def test_element_exists_false_when_nothing_matches(ctx, page):
    assert not await _web_eval({"element_exists": "input"}, ctx, _with_elements(page, 0))


async def test_element_exists_fails_closed_on_error(ctx, page):
    """Unlike an unknown condition, a broken selector skips the step."""
    page.locator.side_effect = RuntimeError("detached frame")
    assert not await _web_eval({"element_exists": "#gone"}, ctx, page)


# ── Combinators ───────────────────────────────────────────────────────────────

async def test_not_inverts(ctx, page):
    assert not await _web_eval({"not": {"url_contains": "/account/login"}}, ctx, page)
    assert await _web_eval({"not": {"url_contains": "/checkout"}}, ctx, page)


async def test_all_requires_every_condition(ctx, page):
    assert await _web_eval(
        {"all": [{"url_contains": "/account"}, {"context_greater_than": {"key": "count", "value": 1}}]},
        ctx, page)
    assert not await _web_eval(
        {"all": [{"url_contains": "/account"}, {"url_contains": "/checkout"}]},
        ctx, page)


async def test_any_requires_one_condition(ctx, page):
    assert await _web_eval(
        {"any": [{"url_contains": "/checkout"}, {"url_contains": "/account"}]}, ctx, page)
    assert not await _web_eval(
        {"any": [{"url_contains": "/checkout"}, {"url_contains": "/cart"}]}, ctx, page)


async def test_empty_all_is_true_and_empty_any_is_false(ctx, page):
    assert await _web_eval({"all": []}, ctx, page)
    assert not await _web_eval({"any": []}, ctx, page)


async def test_combinators_nest(ctx, page):
    condition = {"all": [
        {"not": {"url_contains": "/checkout"}},
        {"any": [
            {"context_equals": {"key": "count", "value": 99}},
            {"context_between": {"key": "count", "min": 1, "max": 10}},
        ]},
    ]}
    assert await _web_eval(condition, ctx, page)


# ── Unknown conditions ────────────────────────────────────────────────────────

async def test_an_unknown_condition_raises(ctx, page):
    """
    It used to fail open: a typo'd key logged a warning and ran the step, so a
    guard that was never evaluated looked exactly like a guard that passed.
    That is the one outcome a guard must not have.

    Raising here is what lets PlanValidator catch it before a session opens —
    see test_plan_validator. StepRunner still catches the exception and runs
    the step, so a plan that somehow reaches runtime unvalidated degrades the
    way it always did rather than dying mid-run.
    """
    with pytest.raises(UnknownConditionError, match="contxt_equals"):
        await _web_eval({"contxt_equals": {"key": "count", "value": 5}}, ctx, page)


async def test_the_error_lists_what_is_registered(ctx, page):
    with pytest.raises(UnknownConditionError, match="context_equals"):
        await _web_eval({"nonsense": 1}, ctx, page)


# ── Core and web are separate vocabularies ────────────────────────────────────

async def test_a_page_condition_is_unknown_to_the_core_registry(ctx, page):
    """
    url_contains belongs to the web domain. A domain with no page — see
    stepper/sites/_noop/ — should not silently accept a condition it cannot
    evaluate.
    """
    with pytest.raises(UnknownConditionError, match="url_contains"):
        await evaluate_when({"url_contains": "/x"}, ctx, page,
                            conditions=core_conditions())


async def test_core_keeps_the_context_predicates_and_the_combinators():
    names = core_conditions().names()

    assert "context_equals" in names and "context_between" in names
    assert {"all", "any", "not"} <= set(names)
    assert "url_contains" not in names and "element_exists" not in names


async def test_the_web_registry_is_core_plus_two():
    assert set(web_conditions().names()) - set(core_conditions().names()) == {
        "url_contains", "element_exists",
    }


async def test_evaluate_when_defaults_to_core(ctx, page):
    """The default is the domain-free vocabulary, not everything that exists."""
    assert await evaluate_when({"context_equals": {"key": "count", "value": 5}}, ctx, page)
    with pytest.raises(UnknownConditionError):
        await evaluate_when({"element_exists": "input"}, ctx, page)


async def test_first_recognised_key_wins(ctx, page):
    """
    Conditions are checked in a fixed order, not merged — a dict carrying two
    condition keys is decided by whichever the evaluator tests first.
    """
    condition = {"context_equals": {"key": "count", "value": 5}, "url_contains": "/nowhere"}
    assert await _web_eval(condition, ctx, page)
