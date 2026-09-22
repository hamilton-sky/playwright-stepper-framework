"""
`{{name}}` resolved at run time, against what earlier steps stored.

There are two real substitution passes. The planner's runs before the workflow
starts and can only see the `variables` block. This one runs before each step
and reads the ExecutionContext, which is how a value one step produced reaches
the next.

It used to be `StepRunner._resolve_count_vars`, and it was narrower than the
documentation beside it claimed, on two axes at once:

    source   `context.counts` only, so a value written by `store` — which goes
             to the context's generic bucket — was invisible to it.
    scope    `step.extra` only, so a reference in a url, a selector or a `when`
             clause was never substituted at all.

Both limits produced the same failure: the literal string "{{name}}" arriving
at an action as an argument, and dying somewhere that names neither the step
nor the reference. The pass now reads the whole context and walks every data
field, and refuses to dispatch a step carrying a name the context cannot
answer.
"""
from __future__ import annotations

import pytest

from stepper.engine.interfaces import ExecutionContext, StepConfig
from stepper.engine.runner.interpolation import (context_lookup, has_reference,
                                                 mapping_lookup, names_in, resolve)
from stepper.engine.runner.step_runner import _resolve_context_vars, _unresolved_error


@pytest.fixture
def context() -> ExecutionContext:
    ctx = ExecutionContext()
    ctx.set_count("gap", 3)          # what ol_ensure_count writes
    ctx.store("item", "Dune")        # what `store` writes
    ctx.store("zero", 0)
    ctx.store("flag", False)
    ctx.store("rows", [{"a": 1}])
    return ctx


def _lookup(context):
    return context_lookup(context)


# ── Type preservation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("gap", 3), ("item", "Dune"), ("zero", 0), ("flag", False),
])
def test_a_pure_reference_keeps_the_stored_type(context, name, expected):
    """
    Stringifying would turn 3 into "3" and False into "False", which then
    compares wrong in a later `when` clause rather than failing loudly.
    """
    resolved, missing = resolve(f"{{{{{name}}}}}", _lookup(context))

    assert resolved == expected and not missing
    assert type(resolved) is type(expected)


def test_whitespace_around_a_pure_reference_is_tolerated(context):
    assert resolve("  {{ gap }}  ", _lookup(context))[0] == 3


def test_an_embedded_reference_is_stringified(context):
    assert resolve("found {{gap}} books", _lookup(context))[0] == "found 3 books"


def test_an_embedded_container_is_serialised_as_json(context):
    """str(list) emits Python literals, which nothing downstream can parse."""
    assert resolve("data={{rows}}", _lookup(context))[0] == 'data=[{"a": 1}]'


def test_a_stored_none_resolves_rather_than_reporting_missing():
    """
    `None` and `0` are values a step may legitimately have stored, so the
    lookup answers (found, value) rather than using a sentinel.
    """
    ctx = ExecutionContext()
    ctx.store("nothing", None)

    resolved, missing = resolve("{{nothing}}", context_lookup(ctx))

    assert resolved is None and missing == []


def test_the_walk_reaches_into_nested_structures(context):
    node = {"sql": "SELECT 1", "params": ["{{item}}", "{{gap}}"], "n": 7}

    resolved, missing = resolve(node, _lookup(context))

    assert resolved == {"sql": "SELECT 1", "params": ["Dune", 3], "n": 7}
    assert not missing


@pytest.mark.parametrize("scalar", [42, True, None, 3.5])
def test_non_string_scalars_pass_through(scalar, context):
    assert resolve(scalar, _lookup(context))[0] is scalar


def test_the_input_is_not_mutated(context):
    node = {"params": ["{{item}}"]}

    resolve(node, _lookup(context))

    assert node == {"params": ["{{item}}"]}, "run_data_rows reuses steps across rows"


# ── Missing names ─────────────────────────────────────────────────────────────

def test_an_unknown_name_is_reported_and_left_in_place(context):
    resolved, missing = resolve("{{typo}}", _lookup(context))

    assert resolved == "{{typo}}"
    assert missing == ["typo"]


def test_every_missing_name_is_reported_once(context):
    _, missing = resolve(["{{a}}", "{{b}}", "{{a}}"], _lookup(context))

    assert missing == ["a", "b"], "de-duplicated, in the order encountered"


def test_has_reference_skips_a_step_with_no_tokens():
    assert not has_reference({"a": 1, "b": ["x", None]})
    assert has_reference({"a": {"b": ["{{x}}"]}})


def test_names_in_lists_what_the_context_can_answer(context):
    assert names_in(context) == ["flag", "gap", "item", "rows", "zero"]


def test_names_in_omits_an_empty_named_field(context):
    """
    `collected_items` answers its default when empty, so offering it as a
    did-you-mean candidate would send someone the wrong way.
    """
    assert "collected_items" not in names_in(context)

    context.collected_items = ["a"]
    assert "collected_items" in names_in(context)


# ── The two axes this widened ─────────────────────────────────────────────────

def _step(**kw) -> StepConfig:
    kw.setdefault("action", "noop")
    kw.setdefault("description", "a step")
    return StepConfig(**kw)


def test_a_count_in_extra_still_resolves(context):
    """The one case the old pass supported; it must not regress."""
    step, missing = _resolve_context_vars(_step(extra={"limit": "{{gap}}"}), context)

    assert step.extra == {"limit": 3} and not missing


def test_a_stored_value_in_extra_now_resolves(context):
    """
    Axis one. `store` writes the generic bucket and the old pass read `counts`,
    so a value a browser step scraped could not be passed to a later step —
    which is the ordinary shape of a mixed web+db workflow.
    """
    step, missing = _resolve_context_vars(
        _step(extra={"params": ["{{item}}"]}), context)

    assert step.extra == {"params": ["Dune"]} and not missing


@pytest.mark.parametrize("field,value,expected", [
    ("url", "https://example.test/{{gap}}", "https://example.test/3"),
    ("input_value", "{{item}}", "Dune"),
    ("description", "adding {{item}}", "adding Dune"),
])
def test_other_fields_now_resolve_too(context, field, value, expected):
    """Axis two: the old pass walked `step.extra` and nothing else."""
    step, missing = _resolve_context_vars(_step(**{field: value}), context)

    assert getattr(step, field) == expected and not missing


def test_a_selector_can_be_built_from_a_stored_value(context):
    step, _ = _resolve_context_vars(_step(element={"css": ".row-{{gap}}"}), context)

    assert step.element == {"css": ".row-3"}


def test_a_when_clause_operand_resolves(context):
    """
    Conditions read the context directly for their *keys*; this is about their
    operands, which is otherwise impossible to express.
    """
    step, _ = _resolve_context_vars(
        _step(when={"context_equals": {"key": "count", "value": "{{gap}}"}}), context)

    assert step.when == {"context_equals": {"key": "count", "value": 3}}


def test_a_step_with_no_references_is_returned_unchanged(context):
    original = _step(extra={"limit": 5})

    step, missing = _resolve_context_vars(original, context)

    assert step is original, "no copy when there is nothing to substitute"
    assert not missing


def test_an_unresolved_reference_is_reported_not_silently_left(context):
    step, missing = _resolve_context_vars(
        _step(extra={"params": ["{{never_stored}}"]}), context)

    assert missing == ["never_stored"]
    assert step.extra == {"params": ["{{never_stored}}"]}


def test_the_error_names_the_reference_and_what_is_available(context):
    message = _unresolved_error(["never_stored"], context)

    assert "never_stored" in message
    assert "item" in message and "gap" in message


def test_the_error_is_honest_about_an_empty_context():
    assert "(nothing yet)" in _unresolved_error(["x"], ExecutionContext())


# ── The mapping lookup, for sub-step substitution ─────────────────────────────

def test_the_mapping_lookup_reads_a_plain_dict():
    resolved, missing = resolve("{{i}}", mapping_lookup({"i": 4}))

    assert resolved == 4 and not missing


def test_sub_step_substitution_still_leaves_unknown_tokens_alone():
    """
    The deliberate asymmetry. A stray token in a sub-step shows up in a log
    line a person reads; the runner's pass refuses instead, because a token
    that reaches an action's arguments is not cosmetic.
    """
    from stepper.engine.actions.sub_step_mixin import _apply_substitutions

    assert _apply_substitutions("{{typo}}", {"i": 4}) == "{{typo}}"


# ── Through the real runner ───────────────────────────────────────────────────
#
# These exist because the field tests above all pass while the integration is
# wrong. The first version of this change resolved inside _run_step, which runs
# *after* `when` is evaluated and after the observers fire — so a condition
# compared against the literal "{{v}}" and skipped its step, and the start log
# printed a token the report did not contain. Every test above still passed.
# Resolution belongs at the top of the loop, and only a runner-level test says so.

from unittest.mock import MagicMock                                    # noqa: E402

from stepper.engine.interfaces import ActionStrategy, StepResult        # noqa: E402
from stepper.engine.runner.step_runner import StepRunner, StepObserver  # noqa: E402
from stepper.engine.runner.when_eval import core_conditions             # noqa: E402


class _Recorder(ActionStrategy):
    """Records the step it was dispatched with, so a test can read it back."""

    action_name = "recorded"
    domain      = None            # session-agnostic: needs no page

    def __init__(self):
        self.steps = []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.steps.append(step)
        return StepResult(step=step, status="passed")


class _Factory:
    def __init__(self, action):
        self._action = action

    def create(self, name):
        return self._action

    def items(self):
        return [("recorded", self._action)]


class _SeenByObserver(StepObserver):
    def __init__(self):
        self.started = []

    def on_step_start(self, idx, step):
        self.started.append(step)

    def on_step_done(self, idx, result):
        pass

    def on_log(self, message, level="info"):
        pass


def _runner(action, observers=()):
    runner = StepRunner(
        page=object(), action_factory=_Factory(action), resolver=MagicMock(),
        reporter=MagicMock(record_step=MagicMock()),
        conditions=core_conditions(),
    )
    for observer in observers:
        runner.add_observer(observer)
    return runner


async def test_the_action_receives_the_resolved_step(context):
    action = _Recorder()

    await _runner(action).run(
        [_step(action="recorded", extra={"limit": "{{gap}}"})], context)

    assert action.steps[0].extra == {"limit": 3}


async def test_a_when_operand_is_resolved_before_the_condition_runs(context):
    """
    The integration bug. `when` is evaluated in run(), so resolving inside
    _run_step left the operand as the literal "{{gap}}" — the comparison failed
    and the step was silently skipped rather than run.
    """
    action = _Recorder()
    context.set_count("count", 3)

    results, _ = await _runner(action).run([
        _step(action="recorded",
              when={"context_equals": {"key": "count", "value": "{{gap}}"}}),
    ], context)

    assert [r.status for r in results] == ["passed"], "3 == 3, so it must run"
    assert len(action.steps) == 1


async def test_observers_see_the_resolved_step(context):
    """
    The other half: a start log printing "{{item}}" while the report holds
    "Dune" is a log that cannot be matched to its own run.
    """
    seen = _SeenByObserver()

    await _runner(_Recorder(), observers=[seen]).run(
        [_step(action="recorded", description="adding {{item}}")], context)

    assert seen.started[0].description == "adding Dune"


async def test_an_unresolved_reference_fails_the_step_and_stops_the_run(context):
    action = _Recorder()

    results, _ = await _runner(action).run([
        _step(action="recorded", extra={"k": "{{never_stored}}"}),
        _step(action="recorded", description="must not run"),
    ], context)

    assert [r.status for r in results] == ["failed"]
    assert "never_stored" in results[0].error
    assert action.steps == [], "the action must not be dispatched at all"


async def test_continue_on_failure_still_applies_to_an_unresolved_reference(context):
    action = _Recorder()

    results, _ = await _runner(action).run([
        _step(action="recorded", extra={"k": "{{nope}}"}, continue_on_failure=True),
        _step(action="recorded", description="runs anyway"),
    ], context)

    assert [r.status for r in results] == ["failed", "passed"]
