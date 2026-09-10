"""
ParallelAction — the read-only safety gate and both execution modes.

This action is the only place the framework runs steps concurrently, and the
only place a `read_only` mistake has consequences: a write action running twice
against a shared session. The gate that prevents that had no test.

No browser — page, context and launcher are stubs.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.actions.strategies import ParallelAction
from engine.interfaces import ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult


# ── Doubles ───────────────────────────────────────────────────────────────────

class RecordingAction(ActionStrategy):
    """
    Records the page it ran against, so tab-per-sub-step is observable.

    Subclasses supply action_name and read_only. They are ClassVars, so they
    belong on a class — the type checker is right to refuse assigning them to
    an instance.
    """

    action_name = "recording"
    read_only = True
    status = "passed"
    error = ""

    def __init__(self) -> None:
        self.pages: list = []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.pages.append(page)
        return StepResult(step=step, status=self.status, error=self.error)


def recording_action(name: str, read_only: bool = True,
                     status: str = "passed", error: str = "") -> RecordingAction:
    """Build a one-off RecordingAction subclass carrying these class constants."""
    cls = type(f"Recording_{name}", (RecordingAction,), {
        "action_name": name,
        "read_only":   read_only,
        "status":      status,
        "error":       error,
    })
    return cls()


class SlowAction(ActionStrategy):
    """Sleeps, so concurrency is observable in wall-clock terms."""

    action_name = "slow"
    read_only = True

    def __init__(self, delay=0.05):
        self._delay = delay

    async def _execute(self, page, step, resolver, context, behaviour=None):
        await asyncio.sleep(self._delay)
        return StepResult(step=step, status="passed")


class ExplodingAction(ActionStrategy):
    action_name = "exploding"
    read_only = True

    async def _execute(self, page, step, resolver, context, behaviour=None):
        raise RuntimeError("sub-step exploded")


class FakeFactory(ActionFactory):
    def __init__(self, mapping):
        self._mapping = mapping

    def create(self, action_name):
        try:
            return self._mapping[action_name]
        except KeyError:
            raise ValueError(f"Unknown action: '{action_name}'")


@pytest.fixture
def page():
    """Page whose .context spawns closable tabs, and records them."""
    p = MagicMock()
    p.opened_tabs = []

    async def new_page():
        tab = MagicMock()
        tab.close = AsyncMock()
        p.opened_tabs.append(tab)
        return tab

    p.context = MagicMock()
    p.context.new_page = AsyncMock(side_effect=new_page)
    return p


def parallel_step(sub_steps, mode=None):
    extra: dict = {"steps": sub_steps}
    if mode:
        extra["mode"] = mode
    return StepConfig(action="parallel", description="run in parallel", extra=extra)


def run(action, page, step):
    return asyncio.run(action.execute(page, step, MagicMock(), ExecutionContext()))


# ── The safety gate ───────────────────────────────────────────────────────────

def test_a_write_action_is_refused(page):
    writer = recording_action("sd_add_to_cart", read_only=False)
    action = ParallelAction(FakeFactory({"sd_add_to_cart": writer}))

    result = run(action, page, parallel_step([{"action": "sd_add_to_cart"}]))

    assert result.status == "failed"
    assert "write actions not allowed" in result.error
    assert "sd_add_to_cart" in result.error


def test_nothing_runs_when_any_sub_step_is_a_write(page):
    """The gate must refuse the whole batch, not run the safe ones first."""
    reader = recording_action("screenshot", read_only=True)
    writer = recording_action("sd_checkout", read_only=False)
    action = ParallelAction(FakeFactory({"screenshot": reader, "sd_checkout": writer}))

    result = run(action, page, parallel_step([
        {"action": "screenshot"}, {"action": "sd_checkout"},
    ]))

    assert result.status == "failed"
    assert reader.pages == []          # the read-only one never ran either
    assert page.opened_tabs == []      # no tab was even opened


def test_an_unknown_action_is_treated_as_unsafe(page):
    action = ParallelAction(FakeFactory({}))

    result = run(action, page, parallel_step([{"action": "no_such_action"}]))

    assert result.status == "failed"
    assert "no_such_action (unknown)" in result.error


def test_read_only_sub_steps_are_allowed(page):
    reader = recording_action("screenshot", read_only=True)
    action = ParallelAction(FakeFactory({"screenshot": reader}))

    result = run(action, page, parallel_step([{"action": "screenshot"}]))

    assert result.status == "passed"
    assert len(reader.pages) == 1


# ── Empty input ───────────────────────────────────────────────────────────────

def test_no_sub_steps_is_skipped_not_failed(page):
    action = ParallelAction(FakeFactory({}))

    result = run(action, page, parallel_step([]))

    assert result.status == "skipped"
    assert "no sub-steps" in result.error


# ── tabs mode ─────────────────────────────────────────────────────────────────

def test_tabs_mode_gives_each_sub_step_its_own_tab(page):
    reader = recording_action("screenshot", read_only=True)
    action = ParallelAction(FakeFactory({"screenshot": reader}))

    run(action, page, parallel_step([{"action": "screenshot"}] * 3, mode="tabs"))

    assert len(page.opened_tabs) == 3
    assert reader.pages == page.opened_tabs      # each ran on its own tab
    assert page not in reader.pages              # never the parent page


def test_tabs_mode_is_the_default(page):
    reader = recording_action("screenshot", read_only=True)
    action = ParallelAction(FakeFactory({"screenshot": reader}))

    run(action, page, parallel_step([{"action": "screenshot"}] * 2))   # no mode

    assert len(page.opened_tabs) == 2


def test_every_tab_is_closed_even_when_a_sub_step_raises(page):
    action = ParallelAction(FakeFactory({"exploding": ExplodingAction()}))

    result = run(action, page, parallel_step([{"action": "exploding"}] * 2))

    assert result.status == "failed"
    assert len(page.opened_tabs) == 2
    for tab in page.opened_tabs:
        tab.close.assert_awaited_once()


def test_sub_steps_actually_run_concurrently(page):
    """Three 50ms sleeps sequentially would be 150ms; concurrently, ~50ms."""
    action = ParallelAction(FakeFactory({"slow": SlowAction(delay=0.05)}))

    t0 = time.monotonic()
    result = run(action, page, parallel_step([{"action": "slow"}] * 3))
    elapsed = time.monotonic() - t0

    assert result.status == "passed"
    assert elapsed < 0.12, f"took {elapsed:.3f}s — sub-steps look sequential"


# ── Result aggregation ────────────────────────────────────────────────────────

def test_one_failing_sub_step_fails_the_parallel_step(page):
    ok = recording_action("ok", read_only=True)
    bad = recording_action("bad", read_only=True, status="failed", error="nope")
    action = ParallelAction(FakeFactory({"ok": ok, "bad": bad}))

    result = run(action, page, parallel_step([{"action": "ok"}, {"action": "bad"}]))

    assert result.status == "failed"
    assert "nope" in result.error


def test_every_failure_is_reported_not_just_the_first(page):
    a = recording_action("a", read_only=True, status="failed", error="first problem")
    b = recording_action("b", read_only=True, status="failed", error="second problem")
    action = ParallelAction(FakeFactory({"a": a, "b": b}))

    result = run(action, page, parallel_step([{"action": "a"}, {"action": "b"}]))

    assert "first problem" in result.error
    assert "second problem" in result.error


def test_a_raising_sub_step_becomes_a_failure_not_a_crash(page):
    action = ParallelAction(FakeFactory({"exploding": ExplodingAction()}))

    result = run(action, page, parallel_step([{"action": "exploding"}]))

    assert result.status == "failed"
    assert "sub-step exploded" in result.error


# ── isolated_browser mode ─────────────────────────────────────────────────────

def test_isolated_browser_mode_without_a_launcher_fails_clearly(page):
    reader = recording_action("screenshot", read_only=True)
    action = ParallelAction(FakeFactory({"screenshot": reader}), browser_launcher=None)

    result = run(action, page, parallel_step([{"action": "screenshot"}],
                                             mode="isolated_browser"))

    assert result.status == "failed"
    assert "requires a browser_launcher" in result.error
    assert reader.pages == []


def test_isolated_browser_mode_uses_the_launcher_and_releases_every_handle(page):
    handles = []

    async def create_page():
        handle, tab = MagicMock(), MagicMock()
        handles.append(handle)
        return handle, tab

    launcher = MagicMock()
    launcher.create_page = AsyncMock(side_effect=create_page)
    launcher.release = AsyncMock()

    reader = recording_action("screenshot", read_only=True)
    action = ParallelAction(FakeFactory({"screenshot": reader}), browser_launcher=launcher)

    result = run(action, page, parallel_step([{"action": "screenshot"}] * 2,
                                             mode="isolated_browser"))

    assert result.status == "passed"
    assert launcher.create_page.await_count == 2
    assert launcher.release.await_count == 2
    assert page.opened_tabs == []                 # tabs mode was not used


def test_isolated_browser_releases_handles_even_when_a_sub_step_raises(page):
    launcher = MagicMock()
    launcher.create_page = AsyncMock(return_value=(MagicMock(), MagicMock()))
    launcher.release = AsyncMock()

    action = ParallelAction(FakeFactory({"exploding": ExplodingAction()}),
                            browser_launcher=launcher)

    result = run(action, page, parallel_step([{"action": "exploding"}],
                                             mode="isolated_browser"))

    assert result.status == "failed"
    launcher.release.assert_awaited_once()


# ── Declared contract ─────────────────────────────────────────────────────────

def test_parallel_is_itself_read_only():
    """So parallel can nest inside another parallel without tripping the gate."""
    assert ParallelAction(FakeFactory({})).read_only is True
