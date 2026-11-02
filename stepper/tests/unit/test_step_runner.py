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

from stepper.engine.interfaces import (
    ActionFactory,
    ActionStrategy,
    ExecutionContext,
    StepConfig,
    StepObserver,
    StepResult,
)
from stepper.engine.browser.conditions import web_conditions
from stepper.engine.runner.hooks import default_web_hooks
from stepper.engine.runner.step_runner import StepRunner


# ── Doubles ───────────────────────────────────────────────────────────────────

class ScriptedAction(ActionStrategy):
    """Action that returns a scripted sequence of statuses, one per call."""

    action_name = "scripted"
    domain      = "web"      # so this file's web hooks apply to it

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
    domain      = "web"

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
        # The CAPTCHA gate and the auto-screenshot are the web domain's hooks,
        # keyed by domain since M3. Everything this file asserts about them is
        # unchanged; only where they come from is.
        kwargs.setdefault("hooks", {"web": default_web_hooks(screenshots_dir)})
        # url_contains and element_exists are the web domain's conditions, so a
        # runner that is standing in for a browser run has to be given them.
        kwargs.setdefault("conditions", web_conditions())
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


# ── Heal order: strict (opt-in) and default ───────────────────────────────────

class ElementAction(ActionStrategy):
    """Passes only when the step's element is one of `works`; records every element."""

    action_name = "scripted"
    domain      = "web"

    def __init__(self, works=()):
        self._works = [dict(w) for w in works]
        self.elements: list = []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.elements.append(step.element)
        ok = step.element in self._works
        return StepResult(step=step, status="passed" if ok else "failed",
                          error="" if ok else "element not found")


class _TierAI:
    """AIService double: records each task_type and prompt, replies per call."""

    def __init__(self, raise_for=()):
        self.calls: list[dict] = []
        self._raise_for = set(raise_for)

    @property
    def task_types(self):
        return [c["task_type"] for c in self.calls]

    async def chat(self, prompt, task_type="classify", system=""):
        self.calls.append({"prompt": prompt, "task_type": task_type})
        if task_type in self._raise_for:
            raise RuntimeError(f"{task_type}: all providers failed")
        return json.dumps([{"action": "scripted", "description": "a step",
                            "element": {"text": f"fix-{len(self.calls)}"}}])


class _FakeCapture:
    """Stands in for DOMSnapshotCascade.capture and records how it was called."""

    def __init__(self, cfg):
        self._cfg = cfg
        self.calls: list[tuple] = []

    async def __call__(self, *args, **kwargs):
        from stepper.engine.healer.interfaces import DomPayload
        self.calls.append((args, kwargs))
        if self._cfg is not None and not kwargs.get("skip_direct", False):
            return DomPayload("embed_direct", "", dict(self._cfg), 0)
        return DomPayload("scoped", '{"best_match": "PAGE-CONTENT-7"}', None, 40)


@pytest.fixture
def heal_world(monkeypatch, make_runner):
    """A runner over a real AiHealer, with the DOM capture and visual bridge faked."""
    from stepper.engine.ai.service import AIService
    from stepper.engine.healer.ai_healer import AiHealer
    from stepper.engine.healer.dom_snapshot import DOMSnapshotCascade
    from stepper.engine.healer.visual_bridge import VisualBridge
    from typing import cast

    async def _no_bridge(page, s):
        return None

    monkeypatch.setattr(VisualBridge, "check", _no_bridge)

    def _build(*, cfg=None, works=(), raise_for=(), **runner_kw):
        capture = _FakeCapture(cfg)
        monkeypatch.setattr(DOMSnapshotCascade, "capture", capture)
        ai = _TierAI(raise_for)
        action = ElementAction(works)
        healer = AiHealer({"scripted": {"description": "scripted"}},
                          ai_service=cast(AIService, ai))
        runner = make_runner({"scripted": action}, healer=healer, **runner_kw)
        return runner, ai, capture, action
    return _build


_MISSING = {"css": ".gone"}
_STALE   = {"text": "stale-cfg"}


async def test_strict_an_embed_direct_miss_is_free_then_cheap_cheap_big(heal_world, page):
    runner, ai, capture, action = heal_world(cfg=_STALE, strict_heal_order=True,
                                             max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert all("PAGE-CONTENT-7" in c["prompt"] for c in ai.calls)
    assert capture.calls[0][1].get("skip_direct", False) is False
    assert len(capture.calls) == 4
    assert all(kw.get("skip_direct") is True for _, kw in capture.calls[1:])
    assert action.elements[1] == _STALE          # the free try ran the stale cfg
    assert results[0].status == "failed"


async def test_strict_the_third_ai_reply_heals_on_the_big_tier(heal_world):
    runner, ai, _, _ = heal_world(cfg=_STALE, works=[{"text": "fix-3"}],
                                  strict_heal_order=True, max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert results[0].status == "healed"
    assert results[0].healed_element["tier"] == "big"
    assert results[0].heal_attempts == 4         # every iteration, the free one too
    assert results[0].healed_element["healed"] == {"text": "fix-3"}


async def test_strict_no_cfg_goes_cheap_cheap_big(heal_world):
    runner, ai, capture, _ = heal_world(cfg=None, strict_heal_order=True,
                                        max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert len(capture.calls) == 3
    assert results[0].status == "failed"


async def test_strict_a_cfg_that_works_heals_first_with_no_ai_call(heal_world):
    runner, ai, _, _ = heal_world(cfg=_STALE, works=[_STALE],
                                  strict_heal_order=True, max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == []
    assert results[0].status == "healed"
    assert results[0].heal_attempts == 1
    assert results[0].healed_element["tier"] == "embed_direct"


async def test_strict_a_big_model_that_raises_leaves_the_step_failed(heal_world):
    runner, ai, _, _ = heal_world(cfg=None, raise_for=("heal_big",),
                                  strict_heal_order=True, max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types.count("heal") == 2
    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert results[0].status == "failed"


async def test_strict_a_heal_cache_hit_is_named_heal_cache(heal_world):
    cache = MagicMock()
    cache.get.return_value = {"text": "cached"}
    runner, ai, capture, _ = heal_world(cfg=None, works=[{"text": "cached"}],
                                        strict_heal_order=True, max_heal_attempts=3,
                                        cache=cache)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == []
    assert capture.calls == []
    assert results[0].status == "healed"
    assert results[0].healed_element["tier"] == "heal_cache"


async def test_default_an_embed_direct_miss_retries_it_and_never_asks_the_ai(heal_world, page):
    runner, ai, capture, action = heal_world(cfg=_STALE, max_heal_attempts=2)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == []
    assert action.elements == [_MISSING, _STALE, _STALE]
    assert len(capture.calls) == 2
    for args, kwargs in capture.calls:
        assert kwargs == {}
        assert len(args) == 2 and args[0] is page and args[1].element == _MISSING
    assert results[0].status == "failed"


async def test_default_no_cfg_asks_heal_three_times_and_never_heal_big(heal_world):
    runner, ai, _, _ = heal_world(cfg=None, max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == ["heal", "heal", "heal"]
    assert results[0].status == "failed"


async def test_default_a_heal_records_no_tier(heal_world):
    runner, ai, _, _ = heal_world(cfg=None, works=[{"text": "fix-2"}],
                                  max_heal_attempts=3)

    results, _ = await runner.run([step(element=_MISSING)])

    assert ai.task_types == ["heal", "heal"]
    assert results[0].status == "healed"
    assert "tier" not in results[0].healed_element


def test_strict_heal_order_is_off_by_default(make_runner):
    runner = make_runner({"scripted": ScriptedAction(["passed"])})
    assert runner._strict_heal_order is False
