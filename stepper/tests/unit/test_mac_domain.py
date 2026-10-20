"""
The mac domain's mouse actions post real CoreGraphics events.

`mac_click` used to run System Events `click at {x, y}`, which asks the
accessibility element under the point to press itself. Web content in Chrome
ignores that, and osascript still exits 0, so a click on a link "passed"
while nothing happened. These tests pin the route, not the OS: no events are
posted (the mouse child is never run with real coordinates).
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

from stepper.engine.interfaces import StepConfig
from stepper.sites.mac import session as mac_session
from stepper.sites.mac.pages.mac_page import MacPage


class _Handle:
    def __init__(self):
        self.calls = []

    def run_click(self, x, y, timeout_s):
        self.calls.append(("click", x, y))
        return True, "clicked"

    def run_drag(self, x1, y1, x2, y2, steps, timeout_s):
        self.calls.append(("drag", x1, y1, x2, y2, steps))
        return True, "dragged"

    def run_script(self, script, timeout_s):
        self.calls.append(("script", script))
        return True, ""


def _run(action, extra):
    page = _Handle()
    step = StepConfig(action=action.action_name, description="t", extra=extra)
    result = asyncio.run(action._execute(page, step, None, None))
    return result, page.calls


def test_mac_click_is_a_real_mouse_click_not_system_events():
    result, calls = _run(MacPage.MacClickAction(), {"x": 490, "y": -104})
    assert result.status == "passed"
    assert calls == [("click", 490, -104)]          # never ("script", "... click at ...")
    assert result.output == {"x": 490, "y": -104}


def test_mac_click_needs_integer_coordinates():
    result, calls = _run(MacPage.MacClickAction(), {"x": "left"})
    assert result.status == "failed" and calls == []


def test_mac_drag_still_goes_through_the_mouse_child():
    result, calls = _run(MacPage.MacDragAction(), {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "steps": 5})
    assert result.status == "passed"
    assert calls == [("drag", 1, 2, 3, 4, 5)]


def test_the_mouse_child_rejects_bad_arguments_before_touching_coregraphics():
    for args in (["bogus"], ["click", "1"], ["drag", "1", "2", "3"]):
        proc = subprocess.run([sys.executable, "-c", mac_session._MOUSE_PY, *args],
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 4, (args, proc.stderr)
        assert "usage: click x y | drag x1 y1 x2 y2 [steps]" in proc.stderr
