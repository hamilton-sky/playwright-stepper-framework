"""
sites/mac/pages/mac_page.py — The mac domain's six actions.

Like sites/db/, these subclass `ActionStrategy` rather than `GlueAction`:
there are no selectors here, so there is nothing for a POM layer to own.
`page` is the MacHandle MacSession handed over; `resolver` is the
NullResolver every domain gets when it asks for nothing better.

The safety contract, stated plainly because this domain can do anything the
logged-in user can:

* `mac_run_script` runs arbitrary AppleScript and therefore REQUIRES
  `extra.confirm: true` in the workflow step. A workflow file sitting in the
  inbox is remote code execution on the Mac; the confirm flag is the line
  between "the user asked for this" and "a file appeared". The watcher does
  not and cannot supply it — only the workflow author can.
* `mac_click`, `mac_type`, `mac_keypress`, `mac_drag`, `mac_screenshot` are
  narrow UI primitives (coordinates, text, one key, a drag vector, a file
  path). They do not take a confirm flag: the step itself, written by the
  user into a workflow they placed in the inbox, is the confirmation. Keep
  new actions on this side of the line — anything that runs caller-chosen
  code goes behind confirm.

All actions return failed StepResults instead of raising, and AppleScript
string values are escaped (backslash, double quote) rather than interpolated
raw.
"""

from __future__ import annotations

import logging
import time

from stepper.engine.interfaces import (
    ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.pages.base_page_module import PageModule
from stepper.sites.mac.session import DEFAULT_TIMEOUT_S

logger = logging.getLogger(__name__)


def _applescript_string(value: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _timeout_s(step: StepConfig) -> float:
    try:
        return float(step.extra.get("timeout_s", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


# Key names mac_keypress understands, mapped to macOS virtual key codes.
# Anything not in this table and not a single character fails the step rather
# than guessing.
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "escape": 53,
    "esc": 53, "delete": 51, "backspace": 51, "up": 126, "down": 125,
    "left": 123, "right": 124, "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111,
}


class MacPage(PageModule):
    """The whole of the mac domain's action surface."""

    site   = "mac"
    domain = "mac"

    class MacRunScriptAction(ActionStrategy):
        """Run arbitrary AppleScript. Requires extra.confirm: true."""

        action_name = "mac_run_script"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            script = str(step.extra.get("script", "")).strip()
            if not script:
                return StepResult(step=step, status="failed",
                                  error="mac_run_script: extra.script is required")
            if step.extra.get("confirm") is not True:
                return StepResult(
                    step=step, status="failed",
                    error="mac_run_script: refusing without extra.confirm: true — "
                          "arbitrary AppleScript is remote code execution; "
                          "the workflow author must confirm it explicitly")
            ok, out = page.run_script(script, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_run_script: {out}")
            logger.info("mac_run_script: ok (%d chars of output)", len(out))
            return StepResult(step=step, status="passed", output={"output": out})

    class MacClickAction(ActionStrategy):
        """Click at screen coordinates. Needs Accessibility permission.

        A real CoreGraphics mouse click (MacHandle.run_click), not System
        Events `click at`, which web content ignores while reporting success.
        """

        action_name = "mac_click"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            try:
                x = int(step.extra["x"])
                y = int(step.extra["y"])
            except (KeyError, TypeError, ValueError):
                return StepResult(step=step, status="failed",
                                  error="mac_click: extra.x and extra.y are "
                                        "required integers")
            ok, out = page.run_click(x, y, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_click: {out}")
            logger.info("mac_click: (%d, %d)", x, y)
            return StepResult(step=step, status="passed",
                              output={"x": x, "y": y})

    class MacTypeAction(ActionStrategy):
        """Type text into the frontmost app. Needs Accessibility permission."""

        action_name = "mac_type"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            text = str(step.extra.get("text", ""))
            if not text:
                return StepResult(step=step, status="failed",
                                  error="mac_type: extra.text is required")
            script = ('tell application "System Events" to keystroke '
                      + _applescript_string(text))
            ok, out = page.run_script(script, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_type: {out}")
            logger.info("mac_type: %d chars", len(text))
            return StepResult(step=step, status="passed",
                              output={"typed_chars": len(text)})

    class MacKeypressAction(ActionStrategy):
        """Press one key: a name from the key-code table or a single character."""

        action_name = "mac_keypress"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            key = str(step.extra.get("key", "")).strip()
            if not key:
                return StepResult(step=step, status="failed",
                                  error="mac_keypress: extra.key is required")
            lowered = key.lower()
            if lowered in _KEY_CODES:
                script = (f'tell application "System Events" to key code '
                          f'{_KEY_CODES[lowered]}')
            elif len(key) == 1:
                script = ('tell application "System Events" to keystroke '
                          + _applescript_string(key))
            else:
                return StepResult(
                    step=step, status="failed",
                    error=f"mac_keypress: unknown key {key!r} — use a name "
                          f"({', '.join(sorted(_KEY_CODES))}) or one character")
            ok, out = page.run_script(script, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_keypress: {out}")
            logger.info("mac_keypress: %r", key)
            return StepResult(step=step, status="passed", output={"key": key})

    class MacDragAction(ActionStrategy):
        """Drag from (x1, y1) to (x2, y2). Needs Accessibility permission.

        System Events has no drag verb, so the gesture is synthesized with
        CoreGraphics mouse events (press, interpolated drags, release) — see
        MacHandle.run_drag. No extra installs; stdlib ctypes only.
        """

        action_name = "mac_drag"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            try:
                x1 = int(step.extra["x1"])
                y1 = int(step.extra["y1"])
                x2 = int(step.extra["x2"])
                y2 = int(step.extra["y2"])
            except (KeyError, TypeError, ValueError):
                return StepResult(
                    step=step, status="failed",
                    error="mac_drag: extra.x1, extra.y1, extra.x2, extra.y2 "
                          "are required integers")
            try:
                steps = int(step.extra.get("steps", 20))
            except (TypeError, ValueError):
                steps = 20
            ok, out = page.run_drag(x1, y1, x2, y2, steps, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_drag: {out}")
            logger.info("mac_drag: (%d, %d) -> (%d, %d)", x1, y1, x2, y2)
            return StepResult(step=step, status="passed",
                              output={"x1": x1, "y1": y1,
                                      "x2": x2, "y2": y2})

    class MacScreenshotAction(ActionStrategy):
        """Capture all displays to a PNG file.

        Needs Screen Recording permission — the first run makes macOS show
        the consent dialog.
        """

        action_name = "mac_screenshot"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            path = str(step.extra.get("path", "")).strip()
            if not path:
                path = f"/tmp/mac_screenshot_{int(time.time())}.png"
            ok, out = page.run_screenshot(path, _timeout_s(step))
            if not ok:
                return StepResult(step=step, status="failed",
                                  error=f"mac_screenshot: {out}")
            logger.info("mac_screenshot: %s", path)
            return StepResult(step=step, status="passed",
                              output={"path": path})

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(
            registry,
            cls.MacRunScriptAction(),
            cls.MacClickAction(),
            cls.MacTypeAction(),
            cls.MacKeypressAction(),
            cls.MacDragAction(),
            cls.MacScreenshotAction(),
        )
