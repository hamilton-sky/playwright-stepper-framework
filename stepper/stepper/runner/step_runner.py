"""
runner/step_runner.py — Orchestrates step execution.

Pattern: Observer (notifies UI, logger, reporter on each step event)
SRP:  Only responsible for the execution loop. Does NOT know about:
      - how elements are found (→ ElementResolver)
      - what each action does (→ ActionStrategy)
      - how results are reported (→ ReporterStrategy)
      - UI updates (→ StepObserver)

DIP: Depends on interfaces, not concrete classes.
"""

from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path

from stepper.interfaces import (
    StepConfig, StepResult, StepObserver,
    ActionFactory, ReporterStrategy, ExecutionContext
)
from stepper.resolvers.element_resolver import ElementResolver
from stepper.runner.when_eval import evaluate_when

logger = logging.getLogger(__name__)


class StepRunner:
    """
    Iterates over a list of StepConfig, dispatches each to the correct
    ActionStrategy via ActionFactory, and notifies all registered observers.
    """

    def __init__(
        self,
        page,
        action_factory: ActionFactory,
        resolver: ElementResolver,
        reporter: ReporterStrategy,
        screenshots_dir: Path | None = None,
    ):
        self._page            = page
        self._factory         = action_factory
        self._resolver        = resolver
        self._reporter        = reporter
        self._observers: list[StepObserver] = []
        if screenshots_dir is not None:
            self._screenshots_dir: Path | None = Path(screenshots_dir)
            self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._screenshots_dir = None

    def add_observer(self, observer: StepObserver):
        self._observers.append(observer)
        return self

    async def run(self, steps: list[StepConfig],
                  context: ExecutionContext | None = None) -> tuple[list[StepResult], ExecutionContext]:
        ctx = context if context is not None else ExecutionContext()
        results = []

        for idx, step in enumerate(steps):
            self._notify_start(idx, step)

            # Evaluate `when` condition — skip if false
            if step.when:
                try:
                    should_run = await evaluate_when(step.when, ctx, self._page)
                except Exception as e:
                    logger.warning(f"Step {idx+1} when-eval error: {e} — step will run")
                    should_run = True
                if not should_run:
                    result = StepResult(
                        step=step, status="skipped",
                        error=f"when={step.when} evaluated to false"
                    )
                    self._reporter.record_step(result)
                    self._notify_done(idx, result)
                    results.append(result)
                    continue

            t0 = time.monotonic()
            max_attempts = 1 + max(0, step.retry)
            for attempt in range(max_attempts):
                try:
                    action = self._factory.create(step.action)
                    result = await action.execute(self._page, step, self._resolver, ctx)
                except Exception as e:
                    logger.error(f"Step {idx+1} raised: {e}")
                    result = StepResult(step=step, status="failed", error=str(e))

                if result.status != "failed" or attempt == max_attempts - 1:
                    break

                delay_s = step.retry_delay_ms / 1000
                logger.warning(
                    f"Step {idx+1} failed (attempt {attempt+1}/{max_attempts}) "
                    f"— retrying in {step.retry_delay_ms}ms"
                )
                await asyncio.sleep(delay_s)

            result.duration_ms = round((time.monotonic() - t0) * 1000, 1)

            # Auto-screenshot: capture page state after each step if the action
            # didn't already produce one. Framework-level — no POM dependency.
            if self._screenshots_dir and not result.screenshot:
                try:
                    safe_action = step.action.replace("/", "_").replace("\\", "_")
                    shot_path = self._screenshots_dir / f"step_{idx+1:02d}_{safe_action}.png"
                    await self._page.screenshot(path=str(shot_path), full_page=False)
                    result.screenshot = str(shot_path)
                except Exception as _e:
                    logger.debug(f"Auto-screenshot failed for step {idx+1}: {_e}")

            self._reporter.record_step(result)
            self._notify_done(idx, result)
            results.append(result)

            # Hard stop on failure — unless step opts out with continue_on_failure
            if result.status == "failed":
                if step.continue_on_failure:
                    self._notify_log(
                        f"⚠ Step {idx+1} failed but continue_on_failure=true — proceeding",
                        "warning",
                    )
                else:
                    self._notify_log(f"✗ Hard stop at step {idx+1}: {result.error}", "error")
                    break

        return results, ctx

    # ── Observer notifications ─────────────────────────────────────────────────

    def _notify_start(self, idx: int, step: StepConfig):
        for obs in self._observers:
            try:
                obs.on_step_start(idx, step)
            except Exception:
                pass

    def _notify_done(self, idx: int, result: StepResult):
        for obs in self._observers:
            try:
                obs.on_step_done(idx, result)
            except Exception:
                pass

    def _notify_log(self, msg: str, level: str = "info"):
        for obs in self._observers:
            try:
                obs.on_log(msg, level)
            except Exception:
                pass


# ── Built-in Observers ────────────────────────────────────────────────────────

class LoggingObserver(StepObserver):
    """Writes step events to the Python logger."""

    def on_step_start(self, idx: int, step: StepConfig):
        logger.info(f"▶ Step {idx+1}: {step.description or step.action}")

    def on_step_done(self, idx: int, result: StepResult):
        icon = {"passed": "✓", "failed": "✗", "skipped": "○", "warned": "⚠"}.get(
            result.status, "•"
        )
        logger.info(f"{icon} Step {idx+1} → {result.status}")

    def on_log(self, message: str, level: str = "info"):
        getattr(logger, level, logger.info)(message)


class CallbackObserver(StepObserver):
    """
    Bridges the runner to external callbacks (e.g. Tkinter UI, Streamlit).
    Accepts callables so callers don't need to subclass.
    """

    def __init__(
        self,
        on_start=None,
        on_done=None,
        on_log=None,
    ):
        self._on_start = on_start or (lambda *a: None)
        self._on_done  = on_done  or (lambda *a: None)
        self._on_log   = on_log   or (lambda *a: None)

    def on_step_start(self, idx: int, step: StepConfig):
        self._on_start(idx, step)

    def on_step_done(self, idx: int, result: StepResult):
        self._on_done(idx, result)

    def on_log(self, message: str, level: str = "info"):
        self._on_log(message, level)
