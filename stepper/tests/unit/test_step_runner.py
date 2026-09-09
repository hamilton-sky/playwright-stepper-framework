"""
Characterization tests for the StepRunner execution loop.

These pin down what the loop *currently does* — step ordering, when-condition
skips, retry, continue_on_failure, hard stop, observer notification, context
flow, auto-screenshots and the heal-suggestions write. Nothing here asserts a
behaviour anyone designed after the fact; the point is that a refactor of the
wiring around StepRunner cannot quietly change how steps run.

No browser, no network. The page, resolver and reporter are stubs.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.interfaces import (
    ActionFactory,
    ActionStrategy,
    ExecutionContext,
    StepConfig,
    StepObserver,
    StepResult,
)
from engine.runner.step_runner import StepRunner


# ── Doubles ───────────────────────────────────────────────────────────────────

class ScriptedAction(ActionStrategy):
    """Action that returns a scripted sequence of statuses, one per call."""

    action_name = "scripted"

    def __init__(self, statuses=("passed",), on_execute=None):
        self._statuses = list(statuses)
        self._on_execute = on_execute
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls += 1
        if self._on_execute is not None:
            self._on_execute(context)
        status = self._statuses[min(self.calls - 1, len(self._statuses) - 1)]
        return StepResult(step=step, status=status,
                          error="boom" if status == "failed" else "")


class RaisingAction(ActionStrategy):
    action_name = "raising"

    def __init__(self):
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls += 1
        raise RuntimeError("action exploded")


class RecordingObserver(StepObserver):
    def __init__(self):
        self.events: list[tuple] = []

    def on_step_start(self, idx, step):
        self.events.append(("start", idx, step.action))

    def on_step_done(self, idx, result):
        self.events.append(("done", idx, result.status))

    def on_log(self, message, level="info"):
        self.events.append(("log", level, message))


class FakeFactory(ActionFactory):
    """Minimal ActionFactory: maps action name → action instance."""

    def __init__(self, mapping):
        self._mapping = mapping

    def create(self, action_name):
        try:
            return self._mapping[action_name]
        except KeyError:
            raise ValueError(f"Unknown action: '{action_name}'")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def page():
    """Page stub: no CAPTCHA, screenshots succeed, url is stable."""
    p = MagicMock()
    p.query_selector = AsyncMock(return_value=None)   # AntiDetection finds nothing
    p.screenshot = AsyncMock(return_value=None)
    p.url = "https://example.test/start"
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    p.locator.return_value = loc
    return p


@pytest.fixture
def behaviour():
    """HumanBehaviour stub — the real one sleeps between every step."""
    b = MagicMock()
    b.inter_step_delay = AsyncMock(return_value=None)
    return b


@pytest.fixture
def reporter():
    r = MagicMock()
    r.record_step = MagicMock()
    return r


@pytest.fixture
def make_runner(page, behaviour, reporter):
    def _make(mapping, screenshots_dir=None, **kwargs):
        return StepRunner(
            page=page,
            action_factory=FakeFactory(mapping),
            resolver=MagicMock(),
            reporter=reporter,
            screenshots_dir=screenshots_dir,
            behaviour=behaviour,
            **kwargs,
        )
    return _make


def step(action="scripted", description="a step", **kwargs):
    return StepConfig(action=action, description=description, **kwargs)


# ── Happy path ────────────────────────────────────────────────────────────────

async def test_runs_every_step_in_order_and_returns_a_result_each(make_runner):
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, ctx = await runner.run([step(description="one"),
                                     step(description="two"),
                                     step(description="three")])

    assert [r.status for r in results] == ["passed", "passed", "passed"]
    assert [r.step.description for r in results] == ["one", "two", "three"]
    assert action.calls == 3
    assert isinstance(ctx, ExecutionContext)


async def test_reporter_records_every_step(make_runner, reporter):
    runner = make_runner({"scripted": ScriptedAction(["passed"])})

    await runner.run([step(), step()])

    assert reporter.record_step.call_count == 2


async def test_observers_see_start_and_done_for_each_step(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["passed"])})
    observer = RecordingObserver()
    runner.add_observer(observer)

    await runner.run([step(), step()])

    lifecycle = [e for e in observer.events if e[0] in ("start", "done")]
    assert lifecycle == [
        ("start", 0, "scripted"), ("done", 0, "passed"),
        ("start", 1, "scripted"), ("done", 1, "passed"),
    ]


async def test_duration_is_recorded_per_step(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["passed"])})

    results, _ = await runner.run([step()])

    assert results[0].duration_ms >= 0.0


# ── when conditions ───────────────────────────────────────────────────────────

async def test_false_when_skips_the_step_without_creating_the_action(make_runner):
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([
        step(description="skipped one", when={"context_key_exists": "nothing_here"}),
        step(description="ran"),
    ])

    assert results[0].status == "skipped"
    assert "evaluated to false" in results[0].skip_reason
    assert results[0].error == ""          # a skip is not an error
    assert action.calls == 1               # only the second step executed


async def test_true_when_runs_the_step(make_runner):
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([
        step(when={"url_contains": "example.test"}),
    ])

    assert results[0].status == "passed"
    assert action.calls == 1


async def test_when_evaluation_error_fails_open_and_runs_the_step(make_runner):
    """
    A condition that raises inside evaluate_when must not swallow the step —
    the runner logs and runs it. ("all" over a non-list raises TypeError.)
    """
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step(when={"all": 123})])

    assert results[0].status == "passed"
    assert action.calls == 1


async def test_element_exists_failure_skips_rather_than_raising(make_runner, page):
    """
    Contrast with the test above: evaluate_when handles element_exists errors
    itself and returns False, so a broken selector *skips* the step. That is
    fail-closed, and only for this one condition type.
    """
    page.locator.side_effect = RuntimeError("detached frame")
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step(when={"element_exists": "#gone"})])

    assert results[0].status == "skipped"
    assert action.calls == 0


# ── Failure handling ──────────────────────────────────────────────────────────

async def test_failed_step_stops_the_run_by_default(make_runner):
    action = ScriptedAction(["failed", "passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step(description="fails"), step(description="never runs")])

    assert [r.status for r in results] == ["failed"]
    assert action.calls == 1


async def test_continue_on_failure_keeps_going(make_runner):
    action = ScriptedAction(["failed", "passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([
        step(description="fails", continue_on_failure=True),
        step(description="still runs"),
    ])

    assert [r.status for r in results] == ["failed", "passed"]
    assert action.calls == 2


async def test_action_exception_becomes_a_failed_result_not_a_crash(make_runner):
    action = RaisingAction()
    runner = make_runner({"raising": action})

    results, _ = await runner.run([step(action="raising")])

    assert results[0].status == "failed"
    assert "action exploded" in results[0].error


async def test_unknown_action_becomes_a_failed_result(make_runner):
    runner = make_runner({})

    results, _ = await runner.run([step(action="does_not_exist")])

    assert results[0].status == "failed"
    assert "Unknown action" in results[0].error


# ── Retry ─────────────────────────────────────────────────────────────────────

async def test_retry_reattempts_until_the_action_passes(make_runner):
    action = ScriptedAction(["failed", "failed", "passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step(retry=2, retry_delay_ms=0)])

    assert results[0].status == "passed"
    assert action.calls == 3


async def test_retry_gives_up_after_the_configured_attempts(make_runner):
    action = ScriptedAction(["failed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step(retry=2, retry_delay_ms=0)])

    assert results[0].status == "failed"
    assert action.calls == 3          # 1 initial + 2 retries


async def test_no_retry_by_default(make_runner):
    action = ScriptedAction(["failed"])
    runner = make_runner({"scripted": action})

    await runner.run([step()])

    assert action.calls == 1


# ── Context flow ──────────────────────────────────────────────────────────────

async def test_context_passed_in_is_the_one_returned(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["passed"])})
    ctx_in = ExecutionContext()
    ctx_in.set_count("count_before", 7)

    _, ctx_out = await runner.run([step()], context=ctx_in)

    assert ctx_out is ctx_in
    assert ctx_out.get_count("count_before") == 7


async def test_mutations_by_one_step_are_visible_to_the_next(make_runner):
    seen: list[int] = []

    def first(ctx):
        ctx.set_count("gap", 3)

    def second(ctx):
        seen.append(ctx.get_count("gap"))

    runner = make_runner({
        "a": ScriptedAction(["passed"], on_execute=first),
        "b": ScriptedAction(["passed"], on_execute=second),
    })

    await runner.run([step(action="a"), step(action="b")])

    assert seen == [3]


# ── CAPTCHA gate ──────────────────────────────────────────────────────────────

async def test_captcha_detected_fails_the_step_before_the_action_runs(make_runner, page):
    page.query_selector = AsyncMock(return_value=object())   # every selector "matches"
    action = ScriptedAction(["passed"])
    runner = make_runner({"scripted": action})

    results, _ = await runner.run([step()])

    assert results[0].status == "failed"
    assert "CAPTCHA" in results[0].error
    assert action.calls == 0


# ── Auto-screenshot ───────────────────────────────────────────────────────────

async def test_auto_screenshot_fills_in_when_the_action_produced_none(make_runner, tmp_path, page):
    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=tmp_path)

    results, _ = await runner.run([step()])

    assert results[0].screenshot.endswith("step_01_scripted.png")
    page.screenshot.assert_awaited_once()


async def test_skip_screenshot_suppresses_the_auto_screenshot(make_runner, tmp_path, page):
    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=tmp_path)

    results, _ = await runner.run([step(skip_screenshot=True)])

    assert results[0].screenshot == ""
    page.screenshot.assert_not_awaited()


async def test_screenshot_failure_does_not_fail_the_step(make_runner, tmp_path, page):
    page.screenshot = AsyncMock(side_effect=RuntimeError("disk full"))
    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=tmp_path)

    results, _ = await runner.run([step()])

    assert results[0].status == "passed"
    assert results[0].screenshot == ""


async def test_no_screenshots_dir_means_no_screenshot(make_runner, page):
    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=None)

    results, _ = await runner.run([step()])

    assert results[0].screenshot == ""
    page.screenshot.assert_not_awaited()


# ── Heal suggestions file ─────────────────────────────────────────────────────

async def test_no_heal_suggestions_file_when_nothing_healed(make_runner, tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=shots)

    await runner.run([step()])

    assert not (tmp_path / "heal_suggestions.json").exists()


async def test_heal_suggestions_are_written_beside_the_screenshots_dir(make_runner, tmp_path):
    """The healer is stubbed; this pins the file location and shape, not the healing."""
    shots = tmp_path / "screenshots"
    shots.mkdir()
    suggestion = {"description": "a step", "original": {"css": ".old"}, "healed": {"css": ".new"}}

    runner = make_runner({"scripted": ScriptedAction(["passed"])}, screenshots_dir=shots)

    async def fake_run_step(idx, step_cfg, steps, ctx):
        return StepResult(step=step_cfg, status="healed"), [suggestion], ctx

    runner._run_step = fake_run_step
    await runner.run([step()])

    written = json.loads((tmp_path / "heal_suggestions.json").read_text(encoding="utf-8"))
    assert written == [suggestion]


# ── Healing is off unless explicitly enabled ──────────────────────────────────

async def test_healer_absent_means_failures_are_not_healed(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["failed"])})

    results, _ = await runner.run([step()])

    assert results[0].status == "failed"
    assert results[0].heal_attempts == 0


async def test_max_heal_attempts_is_capped_at_three(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["passed"])},
                         healer=MagicMock(), max_heal_attempts=99)

    assert runner._max_heal_attempts == 3
