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
from typing import TYPE_CHECKING

import copy
import dataclasses

from engine.interfaces import (
    StepConfig, StepResult, StepObserver,
    ActionFactory, ReporterStrategy, ExecutionContext
)
from engine.resolvers.element_resolver import ElementResolver

if TYPE_CHECKING:
    from engine.resolvers.shadow_runner import ShadowRunner
from engine.runner.when_eval import evaluate_when
from engine.browser.anti_detection import AntiDetection
from engine.browser.human_behaviour import HumanBehaviour
from engine.healer.interfaces import HealerStrategy
from engine.healer.dom_snapshot import DOMSnapshotCascade
from engine.healer.annotator import HealAnnotator
from engine.healer.visual_bridge import VisualBridge
from engine.healer.healing_cache import HealCache

logger = logging.getLogger(__name__)


async def _run_heal_assert(page, spec: dict) -> bool:
    """Return True if all assertions in spec pass, False otherwise."""
    try:
        if "url_contains" in spec:
            if spec["url_contains"] not in page.url:
                return False
        if "url_not_contains" in spec:
            if spec["url_not_contains"] in page.url:
                return False
        if "element_visible" in spec:
            if not await page.locator(spec["element_visible"]).is_visible():
                return False
        if "element_text_contains" in spec:
            sel  = spec["element_text_contains"]["selector"]
            text = spec["element_text_contains"]["text"]
            if text not in await page.locator(sel).inner_text():
                return False
        return True
    except Exception:
        return False


class StepRunner:
    """
    Iterates over a list of StepConfig, dispatches each to the correct
    ActionStrategy via ActionFactory, and notifies all registered observers.
    """

    def __init__(
        self,
        page,
        action_factory: ActionFactory,
        resolver: ElementResolver | ShadowRunner,
        reporter: ReporterStrategy,
        screenshots_dir: Path | None = None,
        behaviour: HumanBehaviour | None = None,
        healer: HealerStrategy | None = None,
        max_heal_attempts: int = 0,
        cache: HealCache | None = None,
    ):
        self._page            = page
        self._factory         = action_factory
        self._resolver        = resolver
        self._reporter        = reporter
        self._behaviour       = behaviour or HumanBehaviour()
        self._healer          = healer
        self._max_heal_attempts = min(max_heal_attempts, 3)  # hard cap
        self._cache           = cache
        self._observers: list[StepObserver] = []
        if screenshots_dir is not None:
            self._screenshots_dir: Path | None = Path(screenshots_dir)
        else:
            self._screenshots_dir = None

    def add_observer(self, observer: StepObserver):
        self._observers.append(observer)
        return self

    async def run(self, steps: list[StepConfig],
                  context: ExecutionContext | None = None) -> tuple[list[StepResult], ExecutionContext]:
        ctx = context if context is not None else ExecutionContext()
        results = []
        heal_suggestions: list[dict] = []

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
                        skip_reason=f"when={step.when} evaluated to false"
                    )
                    self._reporter.record_step(result)
                    self._notify_done(idx, result)
                    results.append(result)
                    continue

            result, step_suggestions, ctx = await self._run_step(idx, step, steps, ctx)
            heal_suggestions.extend(step_suggestions)

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

        if heal_suggestions and self._screenshots_dir:
            import json as _json
            suggestions_path = self._screenshots_dir.parent / "heal_suggestions.json"
            try:
                suggestions_path.write_text(
                    _json.dumps(heal_suggestions, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                logger.info(f"[StepRunner] heal suggestions → {suggestions_path}")
            except Exception as _e:
                logger.debug(f"[StepRunner] could not write heal_suggestions.json: {_e}")

        return results, ctx

    async def _run_step(
        self, idx: int, step: StepConfig, steps: list[StepConfig], ctx: ExecutionContext
    ) -> tuple[StepResult, list[dict], ExecutionContext]:
        # Resolve any remaining {{key}} placeholders against runtime context.
        # Plan-time substitution covers variables{}; this covers context.counts
        # so JSON can write "limit": "{{gap}}" and get the runtime value.
        step = _resolve_count_vars(step, ctx)

        # Pre-step CAPTCHA check — fail fast with a clear message
        captcha = await AntiDetection.detect_captcha(self._page)
        if captcha:
            result = StepResult(
                step=step, status="failed",
                error=f"CAPTCHA detected before step — manual intervention required ({captcha})"
            )
            self._notify_log(f"✗ CAPTCHA wall hit at step {idx+1} — stopping", "error")
            return result, [], ctx

        # Inter-step human-like pause (jittered)
        await self._behaviour.inter_step_delay()

        result = await self._run_retry_loop(idx, step, ctx)

        # Healing loop — fires when: step failed or skipped (element not found),
        # healer injected, step hasn't opted out with heal=False, attempts remain.
        # Note: when-condition skips never reach here (they use `continue` above).
        step_suggestions: list[dict] = []
        if (
            result.status in ("failed", "skipped")
            and self._healer is not None
            and step.heal is not False
            and self._max_heal_attempts > 0
        ):
            result, step_suggestions, ctx = await self._run_heal_loop(idx, step, steps, result, ctx)

        # Auto-screenshot: capture page state after each step if the action
        # didn't already produce one. Framework-level — no POM dependency.
        if self._screenshots_dir and not result.screenshot and not step.skip_screenshot:
            try:
                safe_action = step.action.replace("/", "_").replace("\\", "_")
                shot_path = self._screenshots_dir / f"step_{idx+1:02d}_{safe_action}.png"
                await self._page.screenshot(path=str(shot_path), full_page=False)
                result.screenshot = str(shot_path)
            except Exception as _e:
                logger.debug(f"Auto-screenshot failed for step {idx+1}: {_e}")

        return result, step_suggestions, ctx

    async def _run_retry_loop(
        self, idx: int, step: StepConfig, ctx: ExecutionContext
    ) -> StepResult:
        t0 = time.monotonic()
        max_attempts = 1 + max(0, step.retry)
        result: StepResult = StepResult(step=step, status="failed", error="no attempts made")
        for attempt in range(max_attempts):
            try:
                action = self._factory.create(step.action)
                self._resolver.set_context_description(step.description)
                result = await action.execute(self._page, step, self._resolver, ctx, self._behaviour)
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
        return result

    async def _run_heal_loop(
        self, idx: int, step: StepConfig, steps: list[StepConfig],
        result: StepResult, ctx: ExecutionContext
    ) -> tuple[StepResult, list[dict], ExecutionContext]:
        new_suggestions: list[dict] = []
        heal_attempt = 0
        while heal_attempt < self._max_heal_attempts:
            heal_attempt += 1
            self._notify_log(
                f"⚕ Healing step {idx+1} (attempt {heal_attempt}/{self._max_heal_attempts})",
                "warning",
            )
            try:
                cached_cfg: dict | None = None
                if self._cache:
                    cached_cfg = self._cache.get(step)
                if self._cache and cached_cfg is not None:
                    self._notify_log(
                        f"⚕ [HealCache] HIT for '{step.action}' — skipping cascade", "warning"
                    )
                    healed_step = dataclasses.replace(step, element=cached_cfg)
                    replacement_steps = [healed_step]
                    replacement_runner = StepRunner(
                        page=self._page,
                        action_factory=self._factory,
                        resolver=self._resolver,
                        reporter=self._reporter,
                        screenshots_dir=self._screenshots_dir,
                        behaviour=self._behaviour,
                        healer=None,
                    )
                    for obs in self._observers:
                        replacement_runner.add_observer(obs)
                    rep_results, ctx = await replacement_runner.run(replacement_steps, ctx)
                    if all(r.status != "failed" for r in rep_results):
                        healed_confidence = rep_results[0].confidence if rep_results else 0.0
                        annotated_path = None
                        if self._screenshots_dir and cached_cfg:
                            annotated_path = await HealAnnotator.capture(
                                self._page, cached_cfg,
                                idx + 1, "healed",
                                self._screenshots_dir.parent / "screenshots-healing",
                            )
                        orig_str   = next((f'{k}:"{v}"' for k, v in (step.element or {}).items() if k != "priority"), "?")
                        healed_str = next((f'{k}:"{v}"' for k, v in (cached_cfg  or {}).items() if k != "priority"), "?")
                        self._notify_log(
                            f"⚕  healed step {idx+1} (cache): {orig_str}  ->  {healed_str}", "warning"
                        )
                        result = dataclasses.replace(
                            result, status="healed", error="",
                            confidence=healed_confidence,
                            heal_attempts=heal_attempt,
                            healed_element={"original": step.element, "healed": cached_cfg,
                                            "annotated_screenshot": annotated_path},
                        )
                        new_suggestions.append({
                            "step": idx + 1,
                            "description": step.description,
                            "action": step.action,
                            "original": step.element,
                            "healed": cached_cfg,
                            "annotated_screenshot": annotated_path,
                        })
                        break
                    else:
                        logger.warning(
                            f"[HealCache] stale entry for '{step.action}' — falling through to cascade"
                        )

                bridge_result = await VisualBridge.check(self._page, step)
                if bridge_result == "hidden":
                    self._notify_log(
                        "⚕ Visual bridge: element hidden — injecting scroll_to step", "warning"
                    )
                    inject_result = await self._try_inject_pre_step("scroll_to", step, ctx)
                    if inject_result is not None:
                        orig_result, ctx = inject_result
                        if orig_result.status != "failed":
                            result = dataclasses.replace(result, status="healed", error="")
                            self._notify_log(
                                f"⚕ Step {idx+1} healed via scroll_to injection", "warning"
                            )
                            break
                    self._notify_log(
                        "⚕ scroll_to injection did not fix step — proceeding to cascade", "warning"
                    )
                elif bridge_result == "disabled":
                    self._notify_log(
                        "⚕ Visual bridge: element disabled — injecting wait step", "warning"
                    )
                    inject_result = await self._try_inject_pre_step("wait", step, ctx)
                    if inject_result is not None:
                        orig_result, ctx = inject_result
                        if orig_result.status != "failed":
                            result = dataclasses.replace(result, status="healed", error="")
                            self._notify_log(
                                f"⚕ Step {idx+1} healed via wait injection", "warning"
                            )
                            break
                    result = dataclasses.replace(result, status="failed",
                        error="element found but disabled — wait injection also failed")
                    self._notify_log(
                        "⚕ Visual bridge: element disabled — wait injection failed", "warning"
                    )
                    break

                dom = await DOMSnapshotCascade.capture(self._page, step)
                assert self._healer is not None
                replacement_steps = await self._healer.heal(
                    step, result.error, dom,
                    all_steps=steps,
                    current_index=idx,
                    context_vars=dict(ctx.counts) if ctx.counts else None,
                )

                # Run replacements without healer to prevent infinite recursion
                replacement_runner = StepRunner(
                    page=self._page,
                    action_factory=self._factory,
                    resolver=self._resolver,
                    reporter=self._reporter,
                    screenshots_dir=self._screenshots_dir,
                    behaviour=self._behaviour,
                    healer=None,
                )
                for obs in self._observers:
                    replacement_runner.add_observer(obs)

                rep_results, ctx = await replacement_runner.run(replacement_steps, ctx)

                if all(r.status != "failed" for r in rep_results):
                    # Optional post-heal assertion
                    if step.heal_assert and not await _run_heal_assert(
                        self._page, step.heal_assert
                    ):
                        self._notify_log(
                            f"⚕ Heal attempt {heal_attempt} ran but assertion failed — retrying",
                            "warning",
                        )
                        continue

                    healed_cfg = replacement_steps[0].element if replacement_steps else {}
                    healed_confidence = rep_results[0].confidence if rep_results else 0.0
                    annotated_path = None
                    if self._screenshots_dir and healed_cfg:
                        annotated_path = await HealAnnotator.capture(
                            self._page, healed_cfg,
                            idx + 1, "healed",
                            self._screenshots_dir.parent / "screenshots-healing",
                        )
                    result = dataclasses.replace(
                        result,
                        status="healed",
                        error="",
                        confidence=healed_confidence,
                        heal_attempts=heal_attempt,
                        healed_element={
                            "original": step.element,
                            "healed":   healed_cfg,
                            "annotated_screenshot": annotated_path,
                        },
                    )
                    new_suggestions.append({
                        "step":     idx + 1,
                        "description": step.description,
                        "action":   step.action,
                        "original": step.element,
                        "healed":   healed_cfg,
                        "annotated_screenshot": annotated_path,
                    })
                    if self._cache and healed_cfg:
                        self._cache.put(step, healed_cfg)
                    orig_str   = next((f'{k}:"{v}"' for k, v in (step.element or {}).items() if k != "priority"), "?")
                    healed_str = next((f'{k}:"{v}"' for k, v in (healed_cfg  or {}).items() if k != "priority"), "?")
                    self._notify_log(
                        f"⚕  healed step {idx+1}: {orig_str}  ->  {healed_str}", "warning"
                    )
                    break

            except Exception as heal_exc:
                logger.warning(f"[StepRunner] heal attempt {heal_attempt} failed: {heal_exc}")

        return result, new_suggestions, ctx

    async def _try_inject_pre_step(
        self, pre_action: str, step: StepConfig, ctx: ExecutionContext
    ) -> tuple[StepResult, ExecutionContext] | None:
        """Run a safe pre-step (scroll_to / wait) then re-run the original step.

        The pre-step uses continue_on_failure=True so the original step always runs
        regardless of whether the pre-step succeeded — the caller inspects the
        original step's result to decide if injection fixed the problem.
        Returns (original_step_result, ctx) or None on unexpected exception.
        """
        try:
            pre_step = StepConfig(
                action=pre_action,
                description=f"{pre_action}: {step.description}",
                element=step.element,
                continue_on_failure=True,
            )
            injection_runner = StepRunner(
                page=self._page,
                action_factory=self._factory,
                resolver=self._resolver,
                reporter=self._reporter,
                screenshots_dir=self._screenshots_dir,
                behaviour=self._behaviour,
                healer=None,
            )
            for obs in self._observers:
                injection_runner.add_observer(obs)
            rep_results, ctx = await injection_runner.run([pre_step, step], ctx)
            return rep_results[-1], ctx
        except Exception as e:
            logger.warning(f"[StepRunner] pre-step injection ({pre_action}) failed: {e}")
            return None

    # ── Observer notifications ─────────────────────────────────────────────────

    def _notify(self, method: str, *args):
        for obs in self._observers:
            try:
                getattr(obs, method)(*args)
            except Exception:
                pass

    def _notify_start(self, idx: int, step: StepConfig):
        self._notify("on_step_start", idx, step)

    def _notify_done(self, idx: int, result: StepResult):
        self._notify("on_step_done", idx, result)

    def _notify_log(self, msg: str, level: str = "info"):
        self._notify("on_log", msg, level)


# ── Runtime context variable resolution ──────────────────────────────────────

def _resolve_count_vars(step: StepConfig, ctx: ExecutionContext) -> StepConfig:
    """
    Substitute {{key}} placeholders that reference ctx.counts values set at runtime.

    Scope: only ctx.counts — e.g. "limit": "{{gap}}" resolves to the integer stored
    by ol_ensure_count. Other context fields (collected_items, extracted_data, etc.)
    are handled by ForEachItemAction directly via its own substitution pass.

    Plan-time substitution (JsonFilePlanner) handles the variables{} block.

    Returns a new StepConfig if any substitution occurred; the original otherwise.
    Type preservation: a pure "{{key}}" reference returns the typed value (int/bool).
    """
    if not ctx.counts:
        return step

    # Cheap scan: skip deepcopy entirely when no template tokens are present.
    def _has_template(obj) -> bool:
        if isinstance(obj, str):
            return "{{" in obj
        if isinstance(obj, dict):
            return any(_has_template(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_template(v) for v in obj)
        return False

    if not _has_template(step.extra):
        return step

    def _sub(obj):
        if isinstance(obj, str):
            if obj.startswith("{{") and obj.endswith("}}"):
                key = obj[2:-2].strip()
                if key in ctx.counts:
                    return ctx.counts[key]   # preserves int type
            for k, v in ctx.counts.items():
                obj = obj.replace(f"{{{{{k}}}}}", str(v))
            return obj
        if isinstance(obj, dict):
            return {k: _sub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sub(item) for item in obj]
        return obj

    resolved_extra = _sub(copy.deepcopy(step.extra))
    if resolved_extra == step.extra:
        return step
    return dataclasses.replace(step, extra=resolved_extra)


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
