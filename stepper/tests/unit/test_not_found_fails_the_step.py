"""
A not-found element fails the step. It does not skip it.

`skipped` is what a false `when:` clause produces for a step deliberately not
run. The engine's page primitives used to return the same status when the
resolver found nothing, so a report could not tell "we chose not to" from "we
tried and could not" — and nothing downstream could either:

    success_rate = passed / (passed + failed)        skipped is not in the divisor
    exit code    = 1 if any(status == "failed")      skipped is not a failure

Measured before the fix, clicking a selector that matched nothing on a real
page:

    {"total_steps": 2, "passed": 1, "failed": 0, "skipped": 1, "success_rate": 1.0}
    exit=0

Seven call sites across five actions had it. These tests pin every one, and the
other direction too: a `when:` skip is still a skip, and the healer still fires.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions.factory import build_default_registry
from stepper.engine.interfaces import ExecutionContext, StepConfig


def _resolver(found: bool):
    locator = MagicMock()
    locator.first = MagicMock()
    for name in ("scroll_into_view_if_needed", "hover", "press", "click", "fill",
                 "select_option"):
        setattr(locator, name, AsyncMock())
        setattr(locator.first, name, AsyncMock())
    r = MagicMock()
    r.resolve = AsyncMock(return_value=MagicMock(
        found=found, locator=locator, confidence=1.0, method="css",
    ))
    return r


#: Every action in basic.py that resolves an element, with the extra fields it
#: needs to reach the resolver at all.
RESOLVING_ACTIONS = [
    ("click",          {},                 ""),
    ("fill",           {},                 "a value"),
    ("hover",          {},                 ""),
    ("select",         {"label": "One"},   ""),
    ("scroll_to",      {},                 ""),
    ("keyboard_press", {"key": "Enter"},   ""),
]


def _run(action_name: str, extra: dict, value: str, resolver):
    action = build_default_registry().create(action_name)
    step = StepConfig(action=action_name, description="probe",
                      element={"css": ".nothing-here"}, input_value=value,
                      extra=extra)
    return asyncio.run(action.execute(MagicMock(), step, resolver,
                                      ExecutionContext(), None))


@pytest.mark.parametrize("action_name, extra, value", RESOLVING_ACTIONS,
                         ids=[a for a, _, _ in RESOLVING_ACTIONS])
def test_a_not_found_element_fails_the_step(action_name, extra, value):
    result = _run(action_name, extra, value, _resolver(found=False))

    assert result.status == "failed", (
        f"{action_name} reported {result.status!r} for an element that does not "
        f"exist — a run of it alone would exit 0 with a success rate of 100%"
    )
    assert result.error, f"{action_name} failed without saying why"


@pytest.mark.parametrize("action_name, extra, value", RESOLVING_ACTIONS,
                         ids=[a for a, _, _ in RESOLVING_ACTIONS])
def test_the_same_actions_still_pass_when_the_element_is_there(action_name, extra, value):
    """The off switch. A rule that fails everything is not a rule."""
    result = _run(action_name, extra, value, _resolver(found=True))

    assert result.status == "passed", f"{action_name}: {result.error}"


def test_scroll_to_without_an_element_is_a_configuration_failure():
    """
    The one site that is not a resolver miss. `scroll_to` with no element named
    cannot scroll to anything, and said so as a skip.
    """
    action = build_default_registry().create("scroll_to")
    step = StepConfig(action="scroll_to", description="probe", element={})

    result = asyncio.run(action.execute(MagicMock(), step, _resolver(True),
                                        ExecutionContext(), None))

    assert result.status == "failed"
    assert "no element specified" in result.error


# ── The same defect one branch further down ───────────────────────────────────
#
# Found while verifying the fix above, by healing a deliberately broken
# selector against a real page. The resolver located the button at 45%
# confidence, below the CONFIDENCE_WARN gate, so `click` returned `warned` and
# did not click. `warned` is read by no counter at all:
#
#     {"total_steps": 3, "passed": 2, "failed": 0, "skipped": 0,
#      "success_rate": 1.0}                                        exit=0
#
# Three steps, one of which never happened, and passed + failed + skipped = 2.
# Worse than the skip it replaced — at least a skip was counted. And because
# the heal loop fires on failed-or-skipped, a step the healer exists to rescue
# was dropped instead of healed.


def test_a_click_below_the_confidence_gate_fails():
    from stepper.engine.interfaces import CONFIDENCE_WARN

    resolver = _resolver(found=True)
    resolver.resolve.return_value.confidence = CONFIDENCE_WARN - 0.05
    resolver.resolve.return_value.method = "accessibility-semantic"
    locator = resolver.resolve.return_value.locator

    result = _run("click", {}, "", resolver)

    assert result.status == "failed", (
        "a click that did not happen reported %r, which no counter reads"
        % result.status
    )
    assert locator.first.click.await_count == 0, "it clicked after all"


def test_a_click_above_the_gate_still_acts():
    """The off switch: a confident resolution must still click."""
    result = _run("click", {}, "", _resolver(found=True))

    assert result.status == "passed", result.error


def test_nothing_reports_warned_for_a_step_that_did_not_act():
    """
    `warned` had exactly one producer — this branch — and its own error text
    said the click was skipped. The status stays defined in interfaces.py for
    anything that genuinely wants it; what it must not mean is "did not act".
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine" / "actions" / "basic.py").read_text()

    assert 'status="warned"' not in src


def test_no_action_in_basic_reports_skipped_any_more():
    """
    Static, so it covers the actions these tests do not construct and any added
    later. `skipped` now means one thing: a step deliberately not run.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine" / "actions" / "basic.py").read_text()

    assert 'status="skipped"' not in src, (
        "basic.py reports skipped again — that status belongs to `when:` alone, "
        "and sharing it hides a missing element from every report and exit code"
    )


def test_a_when_clause_skip_is_still_a_skip():
    """
    The other side of the rule. Making not-found fail is only meaningful if
    `skipped` still exists for the case it was meant for.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine" / "runner" / "step_runner.py").read_text()

    assert 'status="skipped"' in src, (
        "nothing produces `skipped` any more — a step a `when:` clause turned "
        "off should not read as a failure"
    )


def test_the_healer_still_fires_on_the_new_status():
    """
    The heal loop used to trigger on `failed` or `skipped`, and not-found
    arrived as the latter. If it had only listened for `skipped`, this change
    would have quietly switched healing off for the case healing exists for.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "engine" / "runner" / "step_runner.py").read_text()

    assert 'result.status in ("failed", "skipped")' in src, (
        "the heal trigger changed shape — check it still covers a not-found "
        "element now that not-found reports failed"
    )
