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
    assert result.output == {"x": 490, "y": -104, "target": "screen"}


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


# ── Aiming, keys and expectations (fake Accessibility; nothing touches the OS) ──

import pytest

from stepper.sites.mac import _ax_child
from stepper.sites.mac.pages import mac_page


class _AXHandle(_Handle):
    def __init__(self, ax=None):
        super().__init__()
        self.ax = ax or {}
        self.ax_calls = []

    def run_ax(self, args, timeout_s):
        self.ax_calls.append(args)
        answer = self.ax.get(args[0])
        if callable(answer):
            answer = answer(args)
        return answer if answer is not None else (False, f"no fake for {args[0]}")


def _run_on(page, action, extra):
    step = StepConfig(action=action.action_name, description="t", extra=extra)
    return asyncio.run(action._execute(page, step, None, None))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mac_page.time, "sleep", lambda s: None)


def test_click_by_element_label_clicks_its_centre_after_raising_the_app():
    page = _AXHandle({"find": (True, {"cx": 416, "cy": -104, "visible": True, "label": "Learn more"})})
    r = _run_on(page, MacPage.MacClickAction(), {"app": "Google Chrome", "element": "Learn more"})
    assert r.status == "passed", r.error
    assert page.calls == [("click", 416, -104)]
    args = page.ax_calls[0]
    assert args[:4] == ["find", "--app", "Google Chrome", "--raise"]
    assert args[args.index("--text") + 1] == "Learn more"
    assert r.output["target"] == "element 'Learn more'"


def test_an_element_outside_the_window_is_not_clicked():
    page = _AXHandle({"find": (True, {"cx": 400, "cy": 3000, "visible": False, "label": "Footer"})})
    r = _run_on(page, MacPage.MacClickAction(), {"element": {"text": "Footer"}})
    assert r.status == "failed" and "scroll it into view" in r.error
    assert page.calls == []


def test_a_missing_element_fails_with_the_lookup_reason():
    page = _AXHandle({"find": (False, "no element labelled 'Nope'")})
    r = _run_on(page, MacPage.MacClickAction(), {"element": "Nope"})
    assert r.status == "failed" and "no element labelled" in r.error


def test_window_relative_click_adds_the_window_origin_read_at_run_time():
    page = _AXHandle({"frame": (True, {"x": -270, "y": -914, "w": 1387, "h": 855, "window_title": "Ex"})})
    r = _run_on(page, MacPage.MacClickAction(),
                {"app": "Google Chrome", "relative": "window", "x": 686, "y": 810})
    assert r.status == "passed"
    assert page.calls == [("click", 416, -104)]
    assert page.ax_calls[0] == ["frame", "--app", "Google Chrome", "--raise"]


def test_raise_false_leaves_the_window_order_alone():
    page = _AXHandle({"frame": (True, {"x": 0, "y": 0, "w": 10, "h": 10})})
    _run_on(page, MacPage.MacClickAction(), {"relative": "window", "x": 1, "y": 1, "raise": False})
    assert page.ax_calls[0] == ["frame"]


def test_drag_can_be_window_relative_too():
    page = _AXHandle({"frame": (True, {"x": 100, "y": 50, "w": 500, "h": 500})})
    r = _run_on(page, MacPage.MacDragAction(),
                {"relative": "window", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "steps": 2})
    assert r.status == "passed"
    assert page.calls == [("drag", 101, 52, 103, 54, 2)]


@pytest.mark.parametrize("key,extra,expected", [
    ("cmd+t", {}, 'keystroke "t" using {command down}'),
    ("cmd+shift+left", {}, "key code 123 using {command down, shift down}"),
    ("pagedown", {}, "key code 121"),
    ("t", {"modifiers": ["ctrl"]}, 'keystroke "t" using {control down}'),
    ("cmd++", {}, 'keystroke "+" using {command down}'),
    ("+", {}, 'keystroke "+"'),
])
def test_keypress_modifiers_and_page_keys(key, extra, expected):
    page = _AXHandle()
    r = _run_on(page, MacPage.MacKeypressAction(), {"key": key, **extra})
    assert r.status == "passed", r.error
    assert page.calls[0][1].endswith(expected)


def test_keypress_rejects_an_unknown_modifier():
    page = _AXHandle()
    r = _run_on(page, MacPage.MacKeypressAction(), {"key": "hyper+t"})
    assert r.status == "failed" and "unknown modifier" in r.error
    assert page.calls == []


def test_expect_turns_a_sent_click_into_a_verified_one():
    titles = iter(["Example Domain - Google Chrome", "Example Domains - Google Chrome"])
    page = _AXHandle({
        "frame": (True, {"x": 0, "y": 0, "w": 10, "h": 10}),
        "front": lambda a: (True, {"app": "Chrome", "window_title": next(titles)}),
    })
    r = _run_on(page, MacPage.MacClickAction(), {
        "relative": "window", "x": 1, "y": 1,
        "expect": {"front_app": "Google Chrome", "window_title_contains": "Example Domains", "timeout_s": 5}})
    assert r.status == "passed", r.error
    assert r.output["expect"] == "met"


def test_an_unmet_expectation_fails_the_step_and_says_what_was_seen():
    page = _AXHandle({
        "frame": (True, {"x": 0, "y": 0, "w": 10, "h": 10}),
        "front": (True, {"app": "Chrome", "window_title": "Example Domain"}),
    })
    r = _run_on(page, MacPage.MacClickAction(), {
        "relative": "window", "x": 1, "y": 1,
        "expect": {"window_title_contains": "IANA", "timeout_s": 0}})
    assert r.status == "failed"
    assert "expected it to contain 'IANA'" in r.error and "'Example Domain'" in r.error


def test_ax_child_matching_prefers_exact_labels_and_skips_invisible_ones():
    cands = [
        {"role": "AXStaticText", "labels": ["Learn more about it"], "x": 0, "y": 0, "w": 9, "h": 9},
        {"role": "AXLink", "labels": ["Learn  More"], "x": 5, "y": 5, "w": 0, "h": 0},
        {"role": "AXLink", "labels": ["learn more"], "x": 1, "y": 1, "w": 9, "h": 9},
    ]
    assert _ax_child.pick(cands, "Learn more")["x"] == 1
    assert _ax_child.pick(cands[:1], "Learn more") is None
    assert _ax_child.pick(cands[:1], "Learn more", "contains")["x"] == 0
    assert _ax_child.pick(cands, "learn more", role="AXStaticText") is None


def test_ax_child_argument_parsing():
    assert _ax_child.parse_args(["find", "--app", "Notes", "--text", "New", "--wait", "2"])["wait"] == 2.0
    for bad in ([], ["find"], ["frame", "--bogus", "x"], ["find", "--text", "a", "--match", "fuzzy"]):
        with pytest.raises(ValueError):
            _ax_child.parse_args(bad)
