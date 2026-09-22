"""
SubStepRunnerMixin and dict_to_step_config — the path every nested step takes.

`for_each_item`, `ensure_login`, `paginate` and `parallel` all run their inner
steps through this mixin. Anything wrong here is wrong inside every loop body in
every workflow, and it surfaces as a confusing failure in the *sub-step*, well
away from the code that caused it.

Two behaviours carry most of the risk.

Substitution has to preserve type. A sub-step written `"limit": "{{count}}"`
where count is the integer 3 must arrive as 3, not "3" — a downstream
`int(...)` would paper over it, but a comparison would not. The rule is that a
*pure* reference keeps its type and an *embedded* one is stringified.

`behaviour` has to be forwarded. Sub-steps that silently ran without it were a
real bug class: the humanisation applied to top-level steps quietly stopped
applying one level down.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions.sub_step_mixin import (
    SubStepRunnerMixin,
    _apply_substitutions,
)
from stepper.engine.interfaces import ExecutionContext, StepResult
from stepper.engine.utils import dict_to_step_config


# ── Substitution: type preservation ───────────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [3, 0, True, False, None, 3.5, ["a", "b"], {"k": "v"}],
)
def test_a_pure_reference_keeps_the_original_type(value):
    """
    "{{count}}" on its own is a reference, not a template. Stringifying it would
    turn an int into "3" and a bool into "True", which then compares wrong in a
    later `when:` clause rather than failing loudly.
    """
    assert _apply_substitutions("{{count}}", {"count": value}) == value


def test_whitespace_around_a_pure_reference_is_tolerated():
    assert _apply_substitutions("  {{ count }}  ", {"count": 7}) == 7


def test_an_embedded_reference_is_stringified():
    """Inside a sentence there is nothing else it could become."""
    assert _apply_substitutions("found {{n}} books", {"n": 3}) == "found 3 books"


def test_an_embedded_container_is_serialised_as_json():
    """
    str(dict) would emit single quotes and Python literals, which is not
    parseable by anything downstream. JSON is.
    """
    result = _apply_substitutions("data={{rows}}", {"rows": [{"a": 1}]})

    assert result == 'data=[{"a": 1}]'


def test_an_unknown_token_is_left_alone():
    """
    Better a visible {{typo}} in a log line than a silent empty string — the
    latter reads as "the value was blank" rather than "the name was wrong".
    """
    assert _apply_substitutions("{{typo}}", {"count": 3}) == "{{typo}}"


def test_substitution_reaches_into_nested_structures():
    raw = {
        "action": "click",
        "element": {"css": ".item-{{idx}}"},
        "extra": {"tags": ["{{name}}", "static"], "limit": "{{limit}}"},
    }

    out = _apply_substitutions(raw, {"idx": 2, "name": "Dune", "limit": 5})

    assert isinstance(out, dict)
    assert out["element"]["css"] == ".item-2"
    assert out["extra"]["tags"] == ["Dune", "static"]
    assert out["extra"]["limit"] == 5, "pure reference in a nested dict keeps its type"


@pytest.mark.parametrize("scalar", [42, True, None, 3.5])
def test_non_string_scalars_pass_through_untouched(scalar):
    assert _apply_substitutions(scalar, {"a": 1}) is scalar


# ── dict_to_step_config ───────────────────────────────────────────────────────

def test_a_minimal_dict_becomes_a_usable_step():
    step = dict_to_step_config({"action": "click"})

    assert step.action == "click"
    assert step.element == {}
    assert step.retry == 0
    assert step.heal is True, "steps opt in to healing by default"


def test_an_explicit_extra_is_used_as_given():
    step = dict_to_step_config({"action": "click", "extra": {"products": ["a"]}})

    assert step.extra == {"products": ["a"]}


def test_unknown_top_level_keys_are_collected_into_extra():
    """Backward compatibility with flat step JSON that predates `extra`."""
    step = dict_to_step_config({"action": "sd_add_to_cart", "products": ["a"], "sort": "az"})

    assert step.extra == {"products": ["a"], "sort": "az"}


def test_an_explicit_extra_stops_the_flat_collection():
    """
    With both shapes present, `extra` wins and the stray keys are dropped rather
    than merged — otherwise a typo'd top-level key would look like it worked.
    """
    step = dict_to_step_config({"action": "x", "extra": {"a": 1}, "stray": 2})

    assert step.extra == {"a": 1}


def test_value_is_accepted_as_an_alias_for_input_value():
    assert dict_to_step_config({"action": "fill", "value": "Dune"}).input_value == "Dune"


def test_input_value_wins_over_value_when_both_are_present():
    step = dict_to_step_config({"action": "fill", "input_value": "real", "value": "alias"})

    assert step.input_value == "real"


def test_heal_can_be_turned_off_per_step():
    assert dict_to_step_config({"action": "click", "heal": False}).heal is False


def test_numeric_fields_are_coerced_from_json_strings():
    """Hand-written workflow JSON quotes numbers more often than you would like."""
    step = dict_to_step_config({"action": "click", "retry": "3", "retry_delay_ms": "500"})

    assert step.retry == 3
    assert step.retry_delay_ms == 500


# ── Sub-step dispatch ─────────────────────────────────────────────────────────

class _Host(SubStepRunnerMixin):
    """Minimal host: the mixin's only requirement is self._factory."""

    def __init__(self, factory):
        self._factory = factory


def _factory(results=None, domain="web"):
    """
    An ActionFactory double. Records every (step, behaviour, session) it
    dispatches and returns the scripted statuses in order.

    The doubles carry a `domain` because every real ActionStrategy does — it is
    what the mixin routes a sub-step's session by (M4). `session` is recorded
    so a test can assert which one a sub-step actually received.
    """
    statuses = list(results or [])
    dispatched: list[dict] = []

    def create(action_name):
        async def execute(page, step, resolver, context, behaviour=None):
            dispatched.append({"action": action_name, "step": step,
                               "behaviour": behaviour, "session": page})
            status = statuses.pop(0) if statuses else "passed"
            return StepResult(step=step, status=status)

        return SimpleNamespace(execute=execute, domain=domain)

    return SimpleNamespace(create=create), dispatched


async def test_every_sub_step_is_dispatched_in_order():
    factory, dispatched = _factory()
    host = _Host(factory)

    results = await host._run_sub_steps(
        [{"action": "click", "description": "a"}, {"action": "fill", "description": "b"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
    )

    assert [d["action"] for d in dispatched] == ["click", "fill"]
    assert [r.status for r in results] == ["passed", "passed"]


async def test_behaviour_is_forwarded_to_every_sub_step():
    """
    The bug this guards: sub-steps ran without the HumanBehaviour that top-level
    steps get, so jitter and hover-dwell silently stopped one level down.
    """
    factory, dispatched = _factory()
    behaviour = object()

    await _Host(factory)._run_sub_steps(
        [{"action": "click"}, {"action": "fill"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
        behaviour=behaviour,
    )

    assert all(d["behaviour"] is behaviour for d in dispatched)


async def test_a_none_behaviour_is_still_forwarded_cleanly():
    """Sub-step dispatch legitimately passes None; nothing may assume otherwise."""
    factory, dispatched = _factory()

    await _Host(factory)._run_sub_steps(
        [{"action": "click"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
    )

    assert dispatched[0]["behaviour"] is None


async def test_substitutions_are_applied_before_dispatch():
    factory, dispatched = _factory()

    await _Host(factory)._run_sub_steps(
        [{"action": "click", "element": {"css": ".row-{{i}}"}, "extra": {"n": "{{i}}"}}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
        substitutions={"i": 4},
    )

    step = dispatched[0]["step"]
    assert step.element == {"css": ".row-4"}
    assert step.extra == {"n": 4}, "pure reference keeps its int type through dispatch"


async def test_the_caller_s_step_dicts_are_not_mutated():
    """
    for_each_item runs the same raw dicts once per item. Substituting in place
    would bake the first item's values into every later iteration.
    """
    factory, _ = _factory()
    raw = [{"action": "click", "element": {"css": ".row-{{i}}"}}]

    await _Host(factory)._run_sub_steps(
        raw, page=MagicMock(), resolver=MagicMock(),
        context=ExecutionContext(), substitutions={"i": 1},
    )

    assert raw[0]["element"]["css"] == ".row-{{i}}"


async def test_stop_on_failure_halts_the_remaining_sub_steps():
    factory, dispatched = _factory(results=["passed", "failed", "passed"])

    results = await _Host(factory)._run_sub_steps(
        [{"action": "a"}, {"action": "b"}, {"action": "c"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
        stop_on_failure=True,
    )

    assert [d["action"] for d in dispatched] == ["a", "b"]
    assert [r.status for r in results] == ["passed", "failed"]


async def test_without_stop_on_failure_the_rest_still_run():
    factory, dispatched = _factory(results=["failed", "passed"])

    results = await _Host(factory)._run_sub_steps(
        [{"action": "a"}, {"action": "b"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
    )

    assert [d["action"] for d in dispatched] == ["a", "b"]
    assert len(results) == 2


@pytest.mark.parametrize("status", ["failed", "skipped", "warned"])
async def test_stop_on_failure_treats_anything_but_passed_as_a_stop(status):
    """"Not passed" is the condition, not "failed" — a skip stops the chain too."""
    factory, dispatched = _factory(results=[status, "passed"])

    await _Host(factory)._run_sub_steps(
        [{"action": "a"}, {"action": "b"}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
        stop_on_failure=True,
    )

    assert [d["action"] for d in dispatched] == ["a"]


# ── `when` on a sub-step ──────────────────────────────────────────────────────

async def test_a_false_when_skips_the_sub_step_without_a_result():
    """
    A skipped sub-step produces no StepResult at all — it is absent from the
    list rather than present with status "skipped".
    """
    factory, dispatched = _factory()
    context = ExecutionContext()
    context.store("count", 0)

    results = await _Host(factory)._run_sub_steps(
        [
            {"action": "a", "when": {"context_greater_than": {"key": "count", "value": 5}}},
            {"action": "b"},
        ],
        page=MagicMock(), resolver=MagicMock(), context=context,
    )

    assert [d["action"] for d in dispatched] == ["b"]
    assert len(results) == 1


async def test_a_true_when_runs_the_sub_step():
    factory, dispatched = _factory()
    context = ExecutionContext()
    context.store("count", 9)

    await _Host(factory)._run_sub_steps(
        [{"action": "a", "when": {"context_greater_than": {"key": "count", "value": 5}}}],
        page=MagicMock(), resolver=MagicMock(), context=context,
    )

    assert [d["action"] for d in dispatched] == ["a"]


async def test_a_when_that_raises_fails_open(monkeypatch):
    """
    Fail-open is the deliberate choice: a broken condition should not silently
    delete a step from the run. Running it and failing visibly beats skipping it
    and passing.
    """
    async def boom(*a, **kw):
        raise RuntimeError("bad condition")

    monkeypatch.setattr("stepper.engine.runner.when_eval.evaluate_when", boom)
    factory, dispatched = _factory()

    await _Host(factory)._run_sub_steps(
        [{"action": "a", "when": {"nonsense": True}}],
        page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
    )

    assert [d["action"] for d in dispatched] == ["a"]


async def test_an_empty_sub_step_list_is_a_no_op():
    factory, dispatched = _factory()

    results = await _Host(factory)._run_sub_steps(
        [], page=MagicMock(), resolver=MagicMock(), context=ExecutionContext(),
    )

    assert results == []
    assert dispatched == []
