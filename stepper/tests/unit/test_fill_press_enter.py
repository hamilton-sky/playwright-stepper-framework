"""
fill types; it does not submit unless asked.

`fill` pressed Enter after every value by default. In a multi-field form that
submits on the first field: in both SauceDemo heal workflows, filling the
password submitted the login before the "Click the Login button" step ran, so
that click never reached the page — let alone the healer. Enter is now opt-in
with `extra.press_enter: true`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions.factory import build_default_registry
from stepper.engine.interfaces import StepConfig


def _found_resolver():
    locator = MagicMock()
    locator.scroll_into_view_if_needed = AsyncMock()
    locator.fill = AsyncMock()
    locator.press = AsyncMock()
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=MagicMock(
        found=True, confidence=0.95, method="css", locator=locator))
    return resolver, locator


async def _fill(extra=None):
    resolver, locator = _found_resolver()
    step = StepConfig(action="fill", description="type the username",
                      element={"css": "#user-name"}, input_value="standard_user",
                      extra=extra or {})
    result = await build_default_registry().create("fill").execute(
        MagicMock(), step, resolver, None, None
    )
    return result, locator


async def test_fill_does_not_press_enter_by_default():
    result, locator = await _fill()

    assert result.status == "passed"
    locator.fill.assert_awaited_once_with("standard_user", timeout=5_000)
    locator.press.assert_not_awaited()


async def test_press_enter_true_submits():
    result, locator = await _fill({"press_enter": True})

    assert result.status == "passed"
    locator.press.assert_awaited_once_with("Enter")


@pytest.mark.parametrize("value", [False, None])
async def test_press_enter_false_or_absent_does_not_submit(value):
    extra = {} if value is None else {"press_enter": value}
    _, locator = await _fill(extra)

    locator.press.assert_not_awaited()

