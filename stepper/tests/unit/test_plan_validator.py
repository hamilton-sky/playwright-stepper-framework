"""
PlanValidator — the gate between a generated plan and a browser.

`python stepper/main.py validate` runs this, and so does the planner before it
hands a plan to the runner. It is the last place a bad step can be caught for
free; past it, finding out costs a browser launch and a partial run.

The design decision worth protecting is that it collects *every* error before
raising. A validator that stops at the first problem turns one `validate` into
one fix per invocation, which for an AI-generated plan with four bad steps is
four round trips.
"""
from __future__ import annotations

import pytest

from stepper.engine.interfaces import StepConfig
from stepper.engine.planner.validator import PlanValidationError, PlanValidator


class _Registry:
    """The only thing PlanValidator asks of a registry is names()."""

    def __init__(self, *names: str):
        self._names = sorted(names)

    def names(self) -> list[str]:
        return self._names


@pytest.fixture
def registry() -> _Registry:
    return _Registry("click", "fill", "navigate", "assert_visible", "sd_login")


def _step(action="click", description="do the thing") -> StepConfig:
    return StepConfig(action=action, description=description)


# ── The happy path ────────────────────────────────────────────────────────────

def test_a_valid_plan_passes_silently(registry):
    PlanValidator.validate([_step("click"), _step("fill")], registry)


def test_an_empty_plan_is_valid(registry):
    """
    Nothing to run is not the validator's problem to reject — an empty workflow
    is a legitimate, if pointless, thing to hold.
    """
    PlanValidator.validate([], registry)


# ── Unknown actions ───────────────────────────────────────────────────────────

def test_an_unregistered_action_is_rejected(registry):
    with pytest.raises(PlanValidationError, match="unknown action 'clik'"):
        PlanValidator.validate([_step("clik")], registry)


def test_a_near_miss_gets_a_suggestion(registry):
    """
    'clik' → 'click' is the single most common way a plan fails. Naming the
    likely fix in the error turns a lookup into a read.
    """
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("clik")], registry)

    assert "did you mean" in str(exc.value)
    assert "'click'" in str(exc.value)


def test_something_unlike_any_action_gets_no_misleading_suggestion(registry):
    """
    A wrong guess is worse than none — "did you mean 'fill'?" for 'xyzzy' sends
    the reader somewhere irrelevant.
    """
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("xyzzy")], registry)

    assert "did you mean" not in str(exc.value)


def test_the_registered_actions_are_listed_once_not_per_error(registry):
    """
    The list is long. Repeating it under each of five unknown actions buries the
    errors themselves in five copies of the same paragraph.
    """
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("nope1"), _step("nope2")], registry)

    assert str(exc.value).count("Registered actions:") == 1


def test_the_action_list_is_omitted_when_no_action_was_unknown(registry):
    """A missing description does not need the whole registry printed at it."""
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("click", description="")], registry)

    assert "Registered actions:" not in str(exc.value)


# ── Missing fields ────────────────────────────────────────────────────────────

def test_a_missing_action_is_rejected(registry):
    with pytest.raises(PlanValidationError, match="missing 'action'"):
        PlanValidator.validate([StepConfig(action="", description="something")], registry)


def test_a_missing_description_is_rejected(registry):
    """
    Not cosmetic: the description is what the semantic resolver embeds and what
    the healer matches on. A step without one degrades both.
    """
    with pytest.raises(PlanValidationError, match="missing 'description'"):
        PlanValidator.validate([_step("click", description="")], registry)


def test_a_step_missing_both_reports_both(registry):
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([StepConfig(action="", description="")], registry)

    message = str(exc.value)
    assert "missing 'action'" in message
    assert "missing 'description'" in message


def test_a_missing_action_is_not_also_reported_as_unknown(registry):
    """
    An empty action is a missing field, not an unrecognised name. Reporting both
    would send the reader looking for an action called "".
    """
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([StepConfig(action="", description="x")], registry)

    assert "unknown action" not in str(exc.value)


# ── Collecting every error ────────────────────────────────────────────────────

def test_every_bad_step_is_reported_in_one_pass(registry):
    """
    The core contract. Stopping at the first error would make fixing a four-error
    plan a four-invocation job.
    """
    steps = [
        _step("click"),                          # fine
        _step("nope"),                           # unknown
        _step("fill", description=""),           # no description
        StepConfig(action="", description=""),   # both
    ]

    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate(steps, registry)

    message = str(exc.value)
    assert "3 validation error(s)" in message
    assert "Step 2" in message and "Step 3" in message and "Step 4" in message
    assert "Step 1" not in message, "the valid step should not be mentioned"


def test_the_exception_carries_the_offending_steps(registry):
    """
    Callers repair plans programmatically; re-parsing the message to find out
    which steps failed would be absurd.
    """
    good, bad = _step("click"), _step("nope")

    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([good, bad], registry)

    assert exc.value.bad_steps == [bad]


def test_step_numbers_are_one_based(registry):
    """They are read against a JSON file a human is looking at, not an array."""
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("nope")], registry)

    assert "Step 1" in str(exc.value)


def test_the_label_falls_back_from_description_to_action(registry):
    """A step with no description still needs to be identifiable in the error."""
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("fill", description="")], registry)

    assert "(fill)" in str(exc.value)


def test_a_wholly_empty_step_still_gets_a_label(registry):
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([StepConfig(action="", description="")], registry)

    assert "<empty step>" in str(exc.value)


# ── Against the real registry ─────────────────────────────────────────────────

def test_the_shipped_workflows_validate_against_the_real_registry():
    """
    The check `main.py validate` performs, run here so it is part of the offline
    suite rather than only the CLI. It is what stops a renamed action silently
    breaking a workflow that nobody runs until release day.
    """
    import json
    from pathlib import Path

    from stepper.engine.actions.factory import build_default_registry
    from stepper.engine.utils import dict_to_step_config

    registry = build_default_registry()
    sites_dir = Path(__file__).resolve().parents[2] / "sites"
    for register_path in sorted(sites_dir.glob("*/register.py")):
        site = register_path.parent.name
        __import__(f"stepper.sites.{site}.register", fromlist=["register"]).register(registry)

    workflows = sorted(sites_dir.glob("*/workflows/*.json"))
    assert workflows, "no workflows found; this test would pass vacuously"

    for path in workflows:
        steps = [dict_to_step_config(s) for s in json.loads(path.read_text())["steps"]]
        PlanValidator.validate(steps, registry)


# ── when-conditions (ticket T4) ───────────────────────────────────────────────
#
# A misspelled condition used to fail open at runtime: the evaluator logged a
# warning and ran the step it was meant to guard. Catching it here is free and
# happens before a session is opened.

def _conditions():
    from stepper.engine.browser.conditions import web_conditions
    return web_conditions()


def test_a_known_condition_validates(registry):
    step = StepConfig(action="click", description="c",
                      when={"context_greater_than": {"key": "n", "value": 0}})

    PlanValidator.validate([step], registry, _conditions())


def test_a_misspelled_condition_is_an_error(registry):
    step = StepConfig(action="click", description="guarded",
                      when={"contxt_greater_than": {"key": "n", "value": 0}})

    with pytest.raises(PlanValidationError) as excinfo:
        PlanValidator.validate([step], registry, _conditions())

    assert "contxt_greater_than" in str(excinfo.value)
    assert "context_greater_than" in str(excinfo.value)   # did-you-mean


def test_conditions_are_only_checked_when_a_registry_is_given(registry):
    """Callers that pass no registry keep the old, unchecked behaviour."""
    step = StepConfig(action="click", description="c", when={"nonsense": 1})

    PlanValidator.validate([step], registry)


def test_a_typo_beside_a_valid_key_is_still_caught(registry):
    """
    At runtime the recognised key wins and the typo is ignored in silence —
    which is exactly the case worth catching, not excusing.
    """
    step = StepConfig(action="click", description="c", when={
        "context_equals": {"key": "n", "value": 1},
        "contxt_equals":  {"key": "n", "value": 1},
    })

    with pytest.raises(PlanValidationError, match="contxt_equals"):
        PlanValidator.validate([step], registry, _conditions())


def test_a_condition_nested_in_a_combinator_is_checked(registry):
    step = StepConfig(action="click", description="c", when={
        "all": [{"url_contains": "/x"}, {"not": {"bogus_condition": 1}}],
    })

    with pytest.raises(PlanValidationError, match="bogus_condition"):
        PlanValidator.validate([step], registry, _conditions())


def test_a_condition_on_a_sub_step_is_checked(registry):
    """
    for_each_item holds its sub-steps as raw dicts in extra, so their `when`
    clauses never reach the validator as StepConfigs of their own.
    """
    step = StepConfig(action="click", description="loop", extra={
        "steps": [{"action": "click", "description": "inner",
                   "when": {"bogus_condition": 1}}],
    })

    with pytest.raises(PlanValidationError, match="bogus_condition"):
        PlanValidator.validate([step], registry, _conditions())


def test_a_web_condition_fails_validation_for_a_domain_without_it(registry):
    """
    The point of a per-domain vocabulary: a noop run naming url_contains is
    caught at validate time rather than raising mid-step.
    """
    from stepper.engine.runner.when_eval import core_conditions

    step = StepConfig(action="click", description="c", when={"url_contains": "/x"})

    with pytest.raises(PlanValidationError, match="url_contains"):
        PlanValidator.validate([step], registry, core_conditions())
