"""
Which domains a plan needs, worked out before anything opens.

This is the read half of M5. The runner already routes each step to its own
domain's session (M2–M4); what was missing is the ability to answer "what will
this workflow open?" without opening it. `validate` prints that answer and
PlanValidator turns a domain no session exists for into a plan error rather
than an UnknownDomainError eight steps into a run.

The risk concentrated here is the walk. Sub-steps live as raw dicts inside
`extra`, so a loop body is exactly where a second domain hides — and since M4
it is a place the runner genuinely hands over a different session. A walk that
stops at the top level would report `[web]` for a workflow that opens a
database halfway through, which is a confident wrong answer.
"""
from __future__ import annotations

import pytest

from stepper.engine.interfaces import StepConfig
from stepper.engine.planner.domains import domains_in_step, domains_used
from stepper.engine.planner.validator import PlanValidationError, PlanValidator


class _Action:
    def __init__(self, domain):
        self.domain = domain


class _Registry:
    """
    Maps a name to an action carrying a domain — what the real ActionRegistry
    does, and the only part of it this walk uses.
    """

    def __init__(self, **domains: str | None):
        self._actions = {name: _Action(domain) for name, domain in domains.items()}

    def names(self) -> list[str]:
        return sorted(self._actions)

    def create(self, name):
        if name not in self._actions:
            raise ValueError(f"Unknown action: '{name}'")
        return self._actions[name]


@pytest.fixture
def registry() -> _Registry:
    return _Registry(click="web", navigate="web", db_query="db",
                     for_each_item="web", parallel="web", wait_seconds=None)


def _step(action="click", **kw) -> StepConfig:
    return StepConfig(action=action, description="do the thing", **kw)


# ── The straightforward reads ─────────────────────────────────────────────────

def test_a_single_domain_plan_reports_that_one_domain(registry):
    assert domains_used([_step("click"), _step("navigate")], registry) == ["web"]


def test_an_empty_plan_needs_nothing(registry):
    assert domains_used([], registry) == []


def test_the_answer_is_sorted_and_deduplicated(registry):
    steps = [_step("db_query"), _step("click"), _step("db_query")]

    assert domains_used(steps, registry) == ["db", "web"]


def test_a_session_agnostic_action_contributes_no_domain(registry):
    """
    An action declaring `domain = None` is handed nothing at runtime (M2). It
    must not cause a domain to open on its behalf, or "needs no session" would
    quietly mean "needs whichever one is first".
    """
    assert domains_used([_step("wait_seconds")], registry) == []


def test_an_unregistered_action_reports_no_domain_rather_than_raising(registry):
    """
    Its real problem is that it is unregistered, which PlanValidator reports
    with a did-you-mean. A second error about its domain would bury that one.
    """
    assert domains_in_step(_step("clik"), registry) == [("clik", None)]


def test_a_step_with_no_action_contributes_nothing(registry):
    assert domains_in_step(StepConfig(action="", description="x"), registry) == []


# ── The walk into sub-steps ───────────────────────────────────────────────────

def test_a_sub_step_s_domain_is_found(registry):
    """The bug this guards: reporting [web] for a workflow that opens a db."""
    step = _step("for_each_item", extra={"steps": [{"action": "db_query"}]})

    assert domains_used([step], registry) == ["db", "web"]


def test_the_walk_reaches_a_loop_nested_inside_a_loop(registry):
    step = _step("parallel", extra={
        "steps": [
            {"action": "for_each_item",
             "steps": [{"action": "db_query", "description": "inner"}]},
        ],
    })

    assert domains_used([step], registry) == ["db", "web"]


def test_the_parent_action_comes_before_its_sub_steps(registry):
    """So an error message built from this reads in the order a person looks."""
    step = _step("for_each_item", extra={"steps": [{"action": "db_query"}]})

    assert domains_in_step(step, registry) == [
        ("for_each_item", "web"), ("db_query", "db"),
    ]


def test_sub_steps_are_found_whatever_key_holds_them(registry):
    """
    flow.py reads `extra["steps"]`, but nothing stops another dispatcher from
    naming its list something else. The walk keys off the `action` key inside
    a dict, not off the name of the list holding it.
    """
    step = _step("parallel", extra={"branches": [{"action": "db_query"}]})

    assert domains_used([step], registry) == ["db", "web"]


def test_a_non_string_action_value_is_ignored(registry):
    """Malformed JSON should fall out as a plan error, not a crash in here."""
    step = _step("parallel", extra={"steps": [{"action": None}, {"action": 3}]})

    assert domains_used([step], registry) == ["web"]


# ── What PlanValidator does with it ───────────────────────────────────────────

def test_a_plan_naming_only_registered_domains_passes(registry):
    PlanValidator.validate([_step("click")], registry, domains=["web", "db"])


def test_a_domain_with_no_session_is_a_plan_error(registry):
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("db_query")], registry, domains=["web"])

    assert "db" in str(exc.value)
    assert "no session for" in str(exc.value)


def test_an_unready_sub_step_domain_is_caught_too(registry):
    """
    The case worth paying for: the top-level step is fine and the failure is
    one level down, which at runtime means a browser launches first.
    """
    step = _step("for_each_item", extra={"steps": [{"action": "db_query"}]})

    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([step], registry, domains=["web"])

    assert "db_query" in str(exc.value)


def test_the_error_lists_the_domains_that_do_exist(registry):
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("db_query")], registry, domains=["web", "noop"])

    message = str(exc.value)
    assert "Registered domains:" in message
    assert "noop" in message and "web" in message


def test_a_near_miss_domain_gets_a_suggestion(registry):
    registry._actions["typo"] = _Action("wbe")

    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("typo")], registry, domains=["web"])

    assert "did you mean" in str(exc.value)


def test_without_domains_the_check_is_off(registry):
    """
    Every caller that predates M5 passes three arguments. They must keep
    validating exactly what they did before.
    """
    PlanValidator.validate([_step("db_query")], registry)


def test_a_session_agnostic_action_is_never_a_domain_error(registry):
    PlanValidator.validate([_step("wait_seconds")], registry, domains=["web"])


def test_an_unregistered_action_reports_only_the_unknown_action(registry):
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator.validate([_step("clik")], registry, domains=["web"])

    message = str(exc.value)
    assert "unknown action" in message
    assert "no session for" not in message, "one problem, one error"
