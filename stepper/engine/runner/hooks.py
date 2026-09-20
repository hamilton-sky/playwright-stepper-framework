"""
runner/hooks.py — Per-step hooks.

StepRunner's loop used to make two browser calls on every step, for every
domain: a CAPTCHA probe before the action and an auto-screenshot after it.
Both are web concerns, both ran unconditionally, and both swallowed their
exceptions — so a non-browser session did not crash on them, it silently
no-opped. That is incidental fault tolerance, not a seam.

They live here now. The runner calls whatever hooks it was given and knows
nothing about what they do; the web domain supplies these two and a domain
with no browser supplies none.

See docs/universal-runner-plan.md — L1, L2, ticket T1.

Writing one
-----------
Subclass StepHook and override the half you need; both default to no-ops.

    class AuditHook(StepHook):
        async def after(self, session, step, result, idx):
            audit_log.write(step.action, result.status)

`before` may abort the step: return a StepResult and the action never runs,
that result is recorded, and the runner reports it like any other. Return
None to proceed. `after` sees the final result — after retries and after
healing — and may mutate it, which is how ScreenshotHook attaches a path.

Hooks are expected to swallow their own failures. A screenshot that cannot be
written must not fail the step it was documenting.
"""

from __future__ import annotations

import logging
from pathlib import Path

from stepper.engine.interfaces import StepConfig, StepResult
from poms.shared.diagnostics import log_swallowed

logger = logging.getLogger(__name__)


class StepHook:
    """
    Base class for per-step hooks. Both methods are no-ops — override one.

    `idx` is the zero-based index of the step within the run, which is what
    the screenshot filenames are numbered from.
    """

    async def before(self, session, step: StepConfig, idx: int) -> StepResult | None:
        """Return a StepResult to abort the step; None to let it run."""
        return None

    async def after(self, session, step: StepConfig, result: StepResult, idx: int) -> None:
        """Observe or amend the finished result. Return value is ignored."""
        return None


class CaptchaHook(StepHook):
    """
    Web domain — fail fast with a clear message when a CAPTCHA wall appears.

    This was `AntiDetection.detect_captcha` hard-wired into _run_step. The
    detector already swallows per-selector errors internally, so a session that
    is not a Playwright page returns None here rather than raising.
    """

    async def before(self, session, step: StepConfig, idx: int) -> StepResult | None:
        from stepper.engine.browser.anti_detection import AntiDetection

        captcha = await AntiDetection.detect_captcha(session)
        if not captcha:
            return None
        return StepResult(
            step=step, status="failed",
            error=f"CAPTCHA detected before step — manual intervention required ({captcha})",
        )


class ScreenshotHook(StepHook):
    """
    Web domain — capture page state after each step, unless the action already
    produced a screenshot of its own or the step opted out with
    skip_screenshot.

    A missing screenshots_dir disables it entirely, which is how `validate` and
    the unit suite run without writing anything.
    """

    def __init__(self, screenshots_dir: Path | None = None):
        self._dir = Path(screenshots_dir) if screenshots_dir is not None else None

    async def after(self, session, step: StepConfig, result: StepResult, idx: int) -> None:
        if not self._dir or result.screenshot or step.skip_screenshot:
            return
        try:
            safe_action = step.action.replace("/", "_").replace("\\", "_")
            shot_path = self._dir / f"step_{idx+1:02d}_{safe_action}.png"
            await session.screenshot(path=str(shot_path), full_page=False)
            result.screenshot = str(shot_path)
        except Exception as _e:
            log_swallowed(f"ScreenshotHook.after[step {idx+1}]", _e, logger)


def default_web_hooks(screenshots_dir: Path | None = None) -> list[StepHook]:
    """
    The pair StepRunner used to hard-wire, in the order it ran them.

    StepRunner falls back to these when no hooks are passed, so every existing
    caller keeps today's behaviour. T3 moves the choice to the composition
    root, at which point the fallback becomes an empty list and the web domain
    supplies this explicitly.
    """
    return [CaptchaHook(), ScreenshotHook(screenshots_dir)]
