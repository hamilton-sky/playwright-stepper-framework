"""
Tests for the domain-free runner seam (ticket T2).

StepRunner used to demand a typed browser resolver and call
set_context_description() on it before every single action. Passing None did
not mean "this domain has no elements" — it meant every step failed with

    'NoneType' object has no attribute 'set_context_description'

recorded as the step's error and retried step.retry times. That is leak L8 in
docs/universal-runner-plan.md, and it is what these tests pin shut.

What is deliberately NOT asserted here: that the run imports no Playwright.
stepper/tests/conftest.py imports playwright at module level (leak L10) and
build_action_registry imports it eagerly (L9), so the assertion belongs with
ticket T7, which fixes both, and T8, which is the receipt.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.resolvers.null_resolver import NoResolverError, NullResolver
from stepper.engine.runner.step_runner import StepRunner
from stepper.engine.session import NullSession, SessionAdapter


# ── Doubles ───────────────────────────────────────────────────────────────────

class CountingAction(ActionStrategy):
    """Touches the context but never the resolver — a non-browser action."""
    action_name = "count"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        context.set_count(step.extra.get("key", "n"), step.extra.get("value", 1))
        return StepResult(step=step, status="passed")


class ResolvingAction(ActionStrategy):
    """Needs an element — the thing a domain without a resolver cannot do."""
    action_name = "click"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        await resolver.resolve(page, step.element, step.description)
        return StepResult(step=step, status="passed")


class DescribingAction(ActionStrategy):
    """Exercises the call the runner makes on every step, via the resolver."""
    action_name = "describe"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        resolver.set_context_description(step.description)
        return StepResult(step=step, status="passed")


class FakeFactory(ActionFactory):
    def __init__(self, mapping):
        self._mapping = mapping

    def create(self, action_name):
        return self._mapping[action_name]


class NoSession:
    """No query_selector, no screenshot, no url — a session, not a page."""


@pytest.fixture
def reporter():
    r = MagicMock()
    r.record_step = MagicMock()
    return r


@pytest.fixture
def behaviour():
    b = MagicMock()
    b.inter_step_delay = AsyncMock(return_value=None)
    return b


@pytest.fixture
def make_runner(reporter, behaviour):
    def _make(mapping, **kwargs):
        kwargs.setdefault("session", NoSession())
        kwargs.setdefault("hooks", [])
        return StepRunner(
            action_factory=FakeFactory(mapping),
            reporter=reporter,
            behaviour=behaviour,
            **kwargs,
        )
    return _make


def step(action="count", description="a step", **kwargs):
    return StepConfig(action=action, description=description, **kwargs)


# ── A run with no resolver at all ─────────────────────────────────────────────

async def test_a_workflow_runs_with_no_resolver(make_runner):
    runner = make_runner({"count": CountingAction()})

    results, ctx = await runner.run([
        step(description="one", extra={"key": "a", "value": 1}),
        step(description="two", extra={"key": "b", "value": 2}),
    ])

    assert [r.status for r in results] == ["passed", "passed"]
    assert ctx.counts == {"a": 1, "b": 2}


async def test_omitting_the_resolver_installs_a_null_one(make_runner):
    runner = make_runner({"count": CountingAction()})

    assert isinstance(runner._resolver, NullResolver)


async def test_the_per_step_description_call_no_longer_explodes(make_runner):
    """
    The regression this ticket exists for: leak L8 turned this into
    "'NoneType' object has no attribute 'set_context_description'".
    """
    runner = make_runner({"describe": DescribingAction()})

    results, _ = await runner.run([step(action="describe")])

    assert results[0].status == "passed"
    assert results[0].error == ""


async def test_when_and_continue_on_failure_still_work_without_a_resolver(make_runner):
    runner = make_runner({"count": CountingAction(), "click": ResolvingAction()})

    results, _ = await runner.run([
        step(description="sets gap", extra={"key": "gap", "value": 3}),
        step(description="runs", when={"context_greater_than": {"key": "gap", "value": 0}}),
        step(description="skipped", when={"context_greater_than": {"key": "gap", "value": 9}}),
        step(action="click", description="needs an element", continue_on_failure=True),
        step(description="still reached"),
    ])

    assert [r.status for r in results] == [
        "passed", "passed", "skipped", "failed", "passed",
    ]


# ── What happens when an action does need one ─────────────────────────────────

async def test_an_action_that_resolves_fails_with_an_explanation(make_runner):
    runner = make_runner({"click": ResolvingAction()})

    results, _ = await runner.run([step(action="click", description="click submit",
                                        element={"css": ".btn"})])

    assert results[0].status == "failed"
    assert "no element resolver" in results[0].error
    assert "click submit" in results[0].error


async def test_the_explanation_is_not_an_attribute_error(make_runner):
    runner = make_runner({"click": ResolvingAction()})

    results, _ = await runner.run([step(action="click")])

    assert "AttributeError" not in results[0].error
    assert "has no attribute" not in results[0].error


async def test_a_real_resolver_is_still_used_when_one_is_given(make_runner):
    resolver = MagicMock()
    resolver.set_context_description = MagicMock()
    runner = make_runner({"count": CountingAction()}, resolver=resolver)

    await runner.run([step(description="a described step")])

    resolver.set_context_description.assert_called_once_with("a described step")


# ── NullResolver on its own ───────────────────────────────────────────────────

def test_the_null_resolver_accepts_any_description():
    assert NullResolver().set_context_description("anything") is None
    assert NullResolver().set_context_description("") is None


async def test_the_null_resolver_names_the_cfg_when_there_is_no_description():
    with pytest.raises(NoResolverError) as excinfo:
        await NullResolver().resolve(None, {"css": ".submit"})

    assert ".submit" in str(excinfo.value)


async def test_the_null_resolver_raises_in_strict_mode_too():
    with pytest.raises(NoResolverError):
        await NullResolver().resolve(None, {"css": ".x"}, "d", strict=True)


# ── The session slot ──────────────────────────────────────────────────────────

async def test_session_is_accepted_in_place_of_page(make_runner):
    marker = NoSession()
    runner = make_runner({"count": CountingAction()}, session=marker)

    assert runner._page is marker


async def test_page_still_works_under_its_old_name(reporter, behaviour):
    marker = object()
    runner = StepRunner(page=marker, action_factory=FakeFactory({}),
                        reporter=reporter, behaviour=behaviour)

    assert runner._page is marker


def test_the_null_session_satisfies_the_adapter_protocol():
    assert isinstance(NullSession(), SessionAdapter)


async def test_the_null_session_opens_something_actions_can_hold():
    session = NullSession("noop")

    opened = await session.open()

    assert opened is not None
    assert await session.close() is None
    assert session.domain == "noop"


# ── The two dependencies that stayed mandatory ────────────────────────────────

def test_a_runner_without_an_action_factory_is_a_type_error(reporter):
    with pytest.raises(TypeError, match="action_factory"):
        StepRunner(page=object(), reporter=reporter)


def test_a_runner_without_a_reporter_is_a_type_error():
    with pytest.raises(TypeError, match="reporter"):
        StepRunner(page=object(), action_factory=FakeFactory({}))
