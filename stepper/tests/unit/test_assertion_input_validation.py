"""
An assertion with nothing to assert must not report "passed".

The failure-propagation work covered the site glue: a POM that reports it did
not act, and glue that turns that into a failed step. The engine-level
*reporting* actions had the same hole from the other side, and it is worse
because it needs no broken page to show up — a misspelled or forgotten key is
enough:

    {"action": "assert_text",  "extra": {"contians": "Welcome", "contains": true}}
      → expected defaulted to "", and "" is inside every string there is.

    {"action": "assert_count", "extra": {}}
      → expected defaulted to 0, no selectors means actual is 0, 0 == 0, green.

Neither step ever looked at the page and both said the page was right. These
tests pin the two halves: the field is required, and a value that is present
but falsy is still a real expectation.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions.factory import build_default_registry
from stepper.engine.interfaces import ExecutionContext, StepConfig


def _run(action, step, page=None, resolver=None):
    return asyncio.run(action.execute(page or MagicMock(), step,
                                      resolver or MagicMock(),
                                      ExecutionContext(), None))


def _text_resolver(text: str):
    """A resolver that finds an element reading `text`."""
    locator = MagicMock()
    locator.first.inner_text = AsyncMock(return_value=text)
    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=MagicMock(found=True, locator=locator, confidence=1.0)
    )
    return resolver


def _page_with(counts: dict[str, int]):
    async def _all(sel):
        return [MagicMock() for _ in range(counts.get(sel, 0))]

    page = MagicMock()
    page.query_selector_all = _all
    return page


# ── assert_text ───────────────────────────────────────────────────────────────

def test_assert_text_without_an_expected_value_fails():
    action   = build_default_registry().create("assert_text")
    resolver = _text_resolver("anything at all")
    step = StepConfig(action="assert_text", description="d",
                      element={"css": ".x"}, extra={"contains": True})

    result = _run(action, step, resolver=resolver)

    assert result.status == "failed", (
        "a missing expected value made `contains` a tautology — it passed "
        "against every element on every page"
    )
    assert "extra.expected" in (result.error or "")


def test_assert_text_never_touches_the_page_without_an_expected_value():
    """A broken step is a configuration error, reported before any lookup."""
    action   = build_default_registry().create("assert_text")
    resolver = _text_resolver("anything at all")
    step = StepConfig(action="assert_text", description="d",
                      element={"css": ".x"}, extra={})

    _run(action, step, resolver=resolver)

    assert resolver.resolve.await_count == 0


def test_an_expected_empty_string_is_still_an_expectation():
    """
    The other half. Absent and empty are different things: `expected: ""` says
    the element reads nothing, and that is a claim the page can contradict.
    """
    action = build_default_registry().create("assert_text")

    empty = StepConfig(action="assert_text", description="d",
                       element={"css": ".x"}, extra={"expected": ""})
    assert _run(action, empty, resolver=_text_resolver("")).status == "passed"
    assert _run(action, empty, resolver=_text_resolver("boom")).status == "failed"


# ── assert_count ──────────────────────────────────────────────────────────────

def test_assert_count_without_an_expected_value_fails():
    action = build_default_registry().create("assert_count")
    step = StepConfig(action="assert_count", description="d",
                      extra={"selectors": [".row"]})

    result = _run(action, step, page=_page_with({".row": 4}))

    assert result.status == "failed", (
        "expected defaulted to 0 — the step passed on an empty page and failed "
        "on a correct one, which is the assertion exactly backwards"
    )
    assert "extra.expected" in (result.error or "")


def test_assert_count_without_anything_to_count_fails():
    action = build_default_registry().create("assert_count")
    step = StepConfig(action="assert_count", description="d",
                      extra={"expected": 0})

    result = _run(action, step, page=_page_with({}))

    assert result.status == "failed", (
        "no selectors and no source means actual is 0 whatever the page holds"
    )
    assert "extra.selectors" in (result.error or "")


def test_assert_count_rejects_a_source_it_cannot_read():
    action = build_default_registry().create("assert_count")
    step = StepConfig(action="assert_count", description="d",
                      extra={"expected": 3, "source": "context.rows"})

    result = _run(action, step, page=_page_with({}))

    assert result.status == "failed"
    assert "context.rows" in (result.error or "")


def test_an_expected_count_of_zero_is_still_an_expectation():
    """`expected: 0` over real selectors is the "nothing left" assertion."""
    action = build_default_registry().create("assert_count")
    step = StepConfig(action="assert_count", description="d",
                      extra={"expected": 0, "selectors": [".row"]})

    assert _run(action, step, page=_page_with({})).status == "passed"
    assert _run(action, step, page=_page_with({".row": 2})).status == "failed"


def test_a_counted_expectation_still_compares_what_it_finds():
    action = build_default_registry().create("assert_count")
    step = StepConfig(action="assert_count", description="d",
                      extra={"expected": 2, "selectors": [".row"]})

    assert _run(action, step, page=_page_with({".row": 2})).status == "passed"
    assert _run(action, step, page=_page_with({".row": 3})).status == "failed"


# ── every workflow on disk still satisfies the rule ───────────────────────────

def _every_step(node):
    """
    Yield every step in a workflow document, however deep.

    Sub-steps are *not* stored where a step's own keys are — `for_each_item`,
    `parallel` and `ensure_login` read them from `step.extra["steps"]`
    (flow.py:57, flow.py:351). A walker that looks for "steps" only at the top
    level of a step therefore never descends into any dispatcher, and this guard
    silently covered nothing nested. So: recurse everything, and treat any dict
    carrying an "action" key as a step. That holds for a nesting key nobody has
    invented yet, which is the point of a repo-wide rule.
    """
    if isinstance(node, dict):
        if "action" in node:
            yield node
        for value in node.values():
            yield from _every_step(value)
    elif isinstance(node, list):
        for item in node:
            yield from _every_step(item)


def test_the_workflow_walker_descends_into_dispatchers():
    """
    A guard that cannot see the thing it guards is worse than none. This pins
    the walker itself against the shape `ol_data_driven.json` actually uses.
    """
    doc = {"steps": [
        {"action": "top"},
        {"action": "for_each_item", "extra": {"steps": [
            {"action": "nested"},
            {"action": "parallel", "extra": {"steps": [{"action": "deep"}]}},
        ]}},
    ]}

    assert [s["action"] for s in _every_step(doc)] == [
        "top", "for_each_item", "nested", "parallel", "deep",
    ]


def test_no_shipped_workflow_relies_on_the_old_defaults():
    """
    The rule is only safe to add because nothing depended on the hole. This
    keeps it that way for workflows written later — at any nesting depth.
    """
    import json
    import pathlib

    offenders = []
    root = pathlib.Path(__file__).resolve().parents[2] / "sites"

    for path in sorted(root.rglob("workflows/*.json")):
        for step in _every_step(json.loads(path.read_text())):
            extra  = step.get("extra", {}) or {}
            action = step.get("action")
            at = f"{path.name} {action}"
            if action == "assert_text" and "expected" not in extra:
                offenders.append(f"{at}: no extra.expected")
            if action == "assert_count":
                if not ("expected" in extra or extra.get("expected_from_context")):
                    offenders.append(f"{at}: no extra.expected")
                if not extra.get("selectors") and not extra.get("source"):
                    offenders.append(f"{at}: nothing to count")

    assert not offenders, "workflow assertions with nothing to assert:\n  " + \
        "\n  ".join(offenders)
