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
* `mac_click` aims at screen points, at an offset inside an app's window
  (`relative: "window"`), or at an element by its label (`element`), and
  every action takes `expect` so a step passes only when its effect is
  visible — see _resolve_point and _check_expect.
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
    "pageup": 116, "pagedown": 121, "home": 115, "end": 119,
    "forwarddelete": 117,
}

# Modifier names for mac_keypress, as "cmd+shift+t" or extra.modifiers.
_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "shift": "shift down",
    "opt": "option down", "option": "option down", "alt": "option down",
    "ctrl": "control down", "control": "control down",
}


def _fail(step: StepConfig, action: str, message: str) -> StepResult:
    return StepResult(step=step, status="failed", error=f"{action}: {message}")


def _target_app(step: StepConfig) -> list[str]:
    app = step.extra.get("app")
    return ["--app", str(app)] if app else []


def _resolve_point(page, step: StepConfig, action: str, x_key="x", y_key="y"):
    """Where to put the mouse, as (x, y, how) in screen points — or an error string.

    * extra.element: {"text": ..., "match": "exact"|"contains", "role": ...}
      — the centre of the first element with that label in the app's front
      window (extra.app, default the frontmost app), found via Accessibility.
    * extra.relative: "window" — extra.x/extra.y are offsets from the top-left
      of that window, read at the moment of the step, so a moved window or a
      different display layout does not make them stale.
    * otherwise extra.x/extra.y are screen points, as before.

    Element and window targets bring the app's window to the front first
    (extra.raise: false to skip), so another window cannot be in the way.
    """
    extra = step.extra
    raise_ = ["--raise"] if extra.get("raise", True) else []
    element = extra.get("element")
    if element is not None:
        if isinstance(element, str):
            element = {"text": element}
        if not isinstance(element, dict) or not str(element.get("text", "")).strip():
            return "extra.element needs a text label"
        args = ["find", *_target_app(step), *raise_, "--text", str(element["text"]),
                "--match", str(element.get("match", "exact")),
                "--wait", str(float(element.get("wait_s", 10)))]
        if element.get("role"):
            args += ["--role", str(element["role"])]
        ok, found = page.run_ax(args, _timeout_s(step) + float(element.get("wait_s", 10)))
        if not ok:
            return found
        if not found.get("visible"):
            return (f"element {found.get('label')!r} is outside the visible window "
                    f"(at {found.get('cx')}, {found.get('cy')}); scroll it into view first")
        return int(found["cx"]), int(found["cy"]), f"element {found.get('label')!r}"
    try:
        x, y = int(extra[x_key]), int(extra[y_key])
    except (KeyError, TypeError, ValueError):
        return f"extra.{x_key} and extra.{y_key} are required integers (or give extra.element)"
    if extra.get("relative") == "window":
        ok, frame = page.run_ax(["frame", *_target_app(step), *raise_], _timeout_s(step))
        if not ok:
            return frame
        return int(frame["x"]) + x, int(frame["y"]) + y, f"window {frame.get('window_title')!r}"
    if extra.get("relative") not in (None, "screen"):
        return 'extra.relative must be "window" or "screen"'
    return x, y, "screen"


def _expect_problem(page, expect: dict, timeout_s: float) -> str | None:
    """None when every expectation holds; otherwise what was seen instead."""
    want_app = expect.get("front_app")
    want_title = expect.get("window_title_contains")
    want_element = expect.get("element")
    ok, front = page.run_ax(["front"], timeout_s)
    if not ok:
        return front
    app = str(front.get("app") or "")
    title = str(front.get("window_title") or "")
    if want_app:
        a, b = str(want_app).casefold(), app.casefold()
        if not (a in b or b in a) or not b:
            return f"front app is {app!r}, expected {want_app!r}"
    if want_title and str(want_title).casefold() not in title.casefold():
        return f"front window is titled {title!r}, expected it to contain {want_title!r}"
    if want_element:
        args = ["find", "--text", str(want_element), "--match", "contains", "--wait", "0"]
        if want_app:
            args[1:1] = ["--app", str(want_app)]
        ok, found = page.run_ax(args, timeout_s)
        if not ok:
            return found
    return None


def _check_expect(page, step: StepConfig, result: StepResult) -> StepResult:
    """Apply extra.expect to a passed step: the step only passes if its effect is there.

    extra.expect: {"front_app": ..., "window_title_contains": ...,
    "element": ..., "timeout_s": 5} — retried every half second until it holds
    or timeout_s runs out. This is what turns "the click was sent" into "the
    click worked".
    """
    expect = step.extra.get("expect")
    if result.status != "passed" or not expect:
        return result
    if not isinstance(expect, dict):
        return _fail(step, step.action, "extra.expect must be an object")
    deadline = time.monotonic() + float(expect.get("timeout_s", 5))
    while True:
        problem = _expect_problem(page, expect, _timeout_s(step))
        if problem is None:
            output = dict(result.output or {})
            output["expect"] = "met"
            return StepResult(step=step, status="passed", output=output)
        if time.monotonic() >= deadline:
            return _fail(step, step.action, f"expectation not met: {problem}")
        time.sleep(0.5)


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
            return _check_expect(page, step, StepResult(
                step=step, status="passed", output={"output": out}))

    class MacClickAction(ActionStrategy):
        """Click at a point, a window offset or an element by its label.

        A real CoreGraphics mouse click (MacHandle.run_click), not System
        Events `click at`, which web content ignores while reporting success.
        See _resolve_point for the three ways to aim. Needs Accessibility.
        """

        action_name = "mac_click"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            point = _resolve_point(page, step, "mac_click")
            if isinstance(point, str):
                return _fail(step, "mac_click", point)
            x, y, how = point
            ok, out = page.run_click(x, y, _timeout_s(step))
            if not ok:
                return _fail(step, "mac_click", out)
            logger.info("mac_click: (%d, %d) via %s", x, y, how)
            return _check_expect(page, step, StepResult(
                step=step, status="passed", output={"x": x, "y": y, "target": how}))

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
            return _check_expect(page, step, StepResult(
                step=step, status="passed", output={"typed_chars": len(text)}))

    class MacKeypressAction(ActionStrategy):
        """Press one key, optionally with modifiers.

        extra.key is "return", "t", "cmd+t", "cmd+shift+left", ... or a plain
        key with extra.modifiers: ["cmd"]. Page keys scroll: pageup, pagedown,
        home, end.
        """

        action_name = "mac_keypress"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            raw = str(step.extra.get("key", "")).strip()
            if not raw:
                return _fail(step, "mac_keypress", "extra.key is required")
            if raw.endswith("++"):                   # "cmd++" is cmd and the + key
                key, named_mods = "+", raw[:-2].split("+")
            elif len(raw) > 1:
                *named_mods, key = raw.split("+")
            else:
                key, named_mods = raw, []
            extra_mods = step.extra.get("modifiers") or []
            if not isinstance(extra_mods, list):
                return _fail(step, "mac_keypress", "extra.modifiers must be a list")
            mods = []
            for m in [*named_mods, *extra_mods]:
                name = str(m).strip().lower()
                if name not in _MODIFIERS:
                    return _fail(step, "mac_keypress",
                                 f"unknown modifier {m!r} — use {', '.join(sorted(_MODIFIERS))}")
                if _MODIFIERS[name] not in mods:
                    mods.append(_MODIFIERS[name])
            using = f" using {{{', '.join(mods)}}}" if mods else ""
            lowered = key.lower()
            if lowered in _KEY_CODES:
                script = (f'tell application "System Events" to key code '
                          f'{_KEY_CODES[lowered]}{using}')
            elif len(key) == 1:
                script = ('tell application "System Events" to keystroke '
                          + _applescript_string(key) + using)
            else:
                return _fail(step, "mac_keypress",
                             f"unknown key {key!r} — use a name "
                             f"({', '.join(sorted(_KEY_CODES))}) or one character")
            ok, out = page.run_script(script, _timeout_s(step))
            if not ok:
                return _fail(step, "mac_keypress", out)
            logger.info("mac_keypress: %r", raw)
            return _check_expect(page, step, StepResult(
                step=step, status="passed", output={"key": raw}))

    class MacDragAction(ActionStrategy):
        """Drag from (x1, y1) to (x2, y2). Needs Accessibility permission.

        System Events has no drag verb, so the gesture is synthesized with
        CoreGraphics mouse events (press, interpolated drags, release) — see
        MacHandle.run_drag. No extra installs; stdlib ctypes only.
        extra.relative: "window" (with extra.app) makes both points offsets
        from that window's top-left, read when the step runs.
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
                return _fail(step, "mac_drag",
                             "extra.x1, extra.y1, extra.x2, extra.y2 are required integers")
            try:
                steps = int(step.extra.get("steps", 20))
            except (TypeError, ValueError):
                steps = 20
            if step.extra.get("relative") == "window":
                raise_ = ["--raise"] if step.extra.get("raise", True) else []
                ok, frame = page.run_ax(["frame", *_target_app(step), *raise_], _timeout_s(step))
                if not ok:
                    return _fail(step, "mac_drag", frame)
                dx, dy = int(frame["x"]), int(frame["y"])
                x1, y1, x2, y2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
            elif step.extra.get("relative") not in (None, "screen"):
                return _fail(step, "mac_drag", 'extra.relative must be "window" or "screen"')
            ok, out = page.run_drag(x1, y1, x2, y2, steps, _timeout_s(step))
            if not ok:
                return _fail(step, "mac_drag", out)
            logger.info("mac_drag: (%d, %d) -> (%d, %d)", x1, y1, x2, y2)
            return _check_expect(page, step, StepResult(
                step=step, status="passed",
                output={"x1": x1, "y1": y1, "x2": x2, "y2": y2}))

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
