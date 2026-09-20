"""
Tests for the per-step hook seam (ticket T1).

The runner used to make two browser calls on every step for every domain: a
CAPTCHA probe before the action and an auto-screenshot after it. Those are now
CaptchaHook and ScreenshotHook, and the loop just calls whatever it was given.

What matters here is that the seam is real — hooks fire in the right place, an
aborting hook stops the action, a broken hook cannot take the run down, and a
domain that passes none gets none. The behaviour of the two web hooks
themselves is still pinned by test_step_runner.py, which constructs runners
without a hooks= argument and therefore exercises the default pair.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, StepConfig, StepResult,
)
from stepper.engine.runner.hooks import (
    CaptchaHook, ScreenshotHook, StepHook, default_web_hooks,
)
from stepper.engine.runner.step_runner import StepRunner


# ── Doubles ───────────────────────────────────────────────────────────────────

class PassingAction(ActionStrategy):
    action_name = "scripted"

    def __init__(self):
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls += 1
        return StepResult(step=step, status="passed")


class FakeFactory(ActionFactory):
    def __init__(self, action):
        self._action = action

    def create(self, action_name):
        return self._action


class RecordingHook(StepHook):
    """Logs the order it was called in, and which step index."""

    def __init__(self, log, name="hook"):
        self._log = log
        self._name = name

    async def before(self, session, step, idx):
        self._log.append((self._name, "before", idx))
        return None

    async def after(self, session, step, result, idx):
        self._log.append((self._name, "after", idx, result.status))


class NoSession:
    """Deliberately has no query_selector and no screenshot."""


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
    def _make(action, **kwargs):
        kwargs.setdefault("session", NoSession())
        return StepRunner(
            action_factory=FakeFactory(action),
            reporter=reporter,
            behaviour=behaviour,
            **kwargs,
        )
    return _make


def step(action="scripted", description="a step", **kwargs):
    return StepConfig(action=action, description=description, **kwargs)


# ── Ordering ──────────────────────────────────────────────────────────────────

async def test_before_runs_ahead_of_the_action_and_after_behind_it(make_runner):
    log: list = []
    action = PassingAction()
    runner = make_runner(action, hooks=[RecordingHook(log)])

    await runner.run([step()])

    assert [entry[1] for entry in log] == ["before", "after"]
    assert action.calls == 1


async def test_every_hook_fires_in_the_order_it_was_given(make_runner):
    log: list = []
    runner = make_runner(
        PassingAction(),
        hooks=[RecordingHook(log, "first"), RecordingHook(log, "second")],
    )

    await runner.run([step()])

    assert [(e[0], e[1]) for e in log] == [
        ("first", "before"), ("second", "before"),
        ("first", "after"),  ("second", "after"),
    ]


async def test_hooks_are_told_which_step_they_are_on(make_runner):
    log: list = []
    runner = make_runner(PassingAction(), hooks=[RecordingHook(log)])

    await runner.run([step(description="one"), step(description="two")])

    assert [e[2] for e in log if e[1] == "before"] == [0, 1]


async def test_after_sees_the_finished_result(make_runner):
    log: list = []
    runner = make_runner(PassingAction(), hooks=[RecordingHook(log)])

    await runner.run([step()])

    assert [e[3] for e in log if e[1] == "after"] == ["passed"]


# ── Aborting ──────────────────────────────────────────────────────────────────

async def test_a_before_hook_returning_a_result_stops_the_action(make_runner, reporter):
    class Wall(StepHook):
        async def before(self, session, step, idx):
            return StepResult(step=step, status="failed", error="blocked by Wall")

    action = PassingAction()
    runner = make_runner(action, hooks=[Wall()])

    results, _ = await runner.run([step()])

    assert action.calls == 0
    assert results[0].status == "failed"
    assert results[0].error == "blocked by Wall"
    reporter.record_step.assert_called_once()


async def test_an_aborted_step_still_hard_stops_the_run(make_runner):
    class Wall(StepHook):
        async def before(self, session, step, idx):
            return StepResult(step=step, status="failed", error="blocked")

    runner = make_runner(PassingAction(), hooks=[Wall()])

    results, _ = await runner.run([step(description="one"), step(description="two")])

    assert len(results) == 1


async def test_an_aborting_hook_skips_the_hooks_after_it(make_runner):
    log: list = []

    class Wall(StepHook):
        async def before(self, session, step, idx):
            return StepResult(step=step, status="failed", error="blocked")

    runner = make_runner(PassingAction(), hooks=[Wall(), RecordingHook(log)])

    await runner.run([step()])

    assert log == []


# ── Fault tolerance ───────────────────────────────────────────────────────────

async def test_a_before_hook_that_raises_is_ignored_and_the_step_runs(make_runner):
    class Broken(StepHook):
        async def before(self, session, step, idx):
            raise RuntimeError("hook exploded")

    action = PassingAction()
    runner = make_runner(action, hooks=[Broken()])

    results, _ = await runner.run([step()])

    assert results[0].status == "passed"
    assert action.calls == 1


async def test_an_after_hook_that_raises_does_not_fail_the_step(make_runner):
    class Broken(StepHook):
        async def after(self, session, step, result, idx):
            raise RuntimeError("hook exploded")

    runner = make_runner(PassingAction(), hooks=[Broken()])

    results, _ = await runner.run([step()])

    assert results[0].status == "passed"


async def test_one_broken_hook_does_not_stop_the_others(make_runner):
    log: list = []

    class Broken(StepHook):
        async def before(self, session, step, idx):
            raise RuntimeError("hook exploded")

    runner = make_runner(PassingAction(), hooks=[Broken(), RecordingHook(log)])

    await runner.run([step()])

    assert [e[1] for e in log] == ["before", "after"]


# ── No hooks at all ───────────────────────────────────────────────────────────

async def test_an_empty_hook_list_touches_the_session_not_at_all(make_runner):
    """
    A session with no query_selector and no screenshot is exactly what a
    non-browser domain hands over. Before T1 this ran the CAPTCHA probe and the
    auto-screenshot against it regardless; both swallowed their errors, so the
    coupling was invisible rather than absent.
    """
    session = NoSession()
    runner = make_runner(PassingAction(), session=session, hooks=[], screenshots_dir=None)

    results, _ = await runner.run([step()])

    assert results[0].status == "passed"
    assert results[0].screenshot == ""


async def test_an_empty_hook_list_writes_no_screenshot_even_with_a_dir(make_runner, tmp_path):
    runner = make_runner(PassingAction(), hooks=[], screenshots_dir=tmp_path)

    results, _ = await runner.run([step()])

    assert results[0].screenshot == ""
    assert list(tmp_path.iterdir()) == []


# ── The default pair ──────────────────────────────────────────────────────────

def test_omitting_hooks_installs_the_web_pair(reporter):
    runner = StepRunner(page=MagicMock(), action_factory=FakeFactory(PassingAction()),
                        reporter=reporter)

    installed = [type(h) for h in runner._hooks]

    assert installed == [CaptchaHook, ScreenshotHook]


def test_default_web_hooks_carries_the_screenshots_dir(tmp_path):
    _captcha, screenshot_hook = default_web_hooks(tmp_path)

    assert screenshot_hook._dir == tmp_path


def test_the_base_hook_is_a_no_op_on_both_halves():
    """Subclasses override one half; the other must stay harmless."""
    import asyncio

    hook = StepHook()
    cfg = step()
    result = StepResult(step=cfg, status="passed")

    assert asyncio.run(hook.before(None, cfg, 0)) is None
    assert asyncio.run(hook.after(None, cfg, result, 0)) is None
    assert result.screenshot == ""


# ── Propagation into sub-runners ──────────────────────────────────────────────

async def test_hooks_reach_the_runner_that_injects_a_pre_step(make_runner):
    """
    The heal path builds fresh StepRunners for its replacement and injected
    steps. A domain's choice of hooks has to survive that, or healing would
    quietly reinstate the browser pair on a non-browser run.
    """
    log: list = []
    runner = make_runner(PassingAction(), hooks=[RecordingHook(log)])

    from stepper.engine.interfaces import ExecutionContext
    await runner._try_inject_pre_step("scripted", step(), ExecutionContext())

    # pre-step + the re-run original, each through before and after
    assert [e[1] for e in log] == ["before", "after", "before", "after"]
