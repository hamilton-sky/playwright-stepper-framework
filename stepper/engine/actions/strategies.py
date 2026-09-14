"""
actions/strategies.py — every ActionStrategy the engine ships, in one namespace.

The classes themselves live in focused modules alongside this one:

    basic.py        page primitives — navigate, click, fill, hover, select,
                    wait, scroll_to, keyboard_press, screenshot
    assertions.py   assert_count / assert_text / assert_visible, and the
                    store_count / store actions that record instead of judge
    data.py         extract_data, load_test_data
    flow.py         actions that dispatch sub-steps — for_each_item,
                    ensure_login, paginate, parallel, run_workflow
    measurement.py  measure_performance, visual_compare
    _common.py      helpers shared by more than one of the above

This module re-exports all of them. It was a single 1331-line file holding 23
classes; splitting it is what the Strategy pattern buys you, and the import
path is kept so nothing downstream has to care.

Import from the specific module in new code — `from stepper.engine.actions.flow
import ParallelAction` says more than the same name pulled out of a bag of
twenty-three.
"""

from __future__ import annotations

from stepper.engine.actions._common import (
    _wait_for,
    _resolve_input_value,
    _fetch_attr,
    _checked_input_value,
)
from stepper.engine.actions.basic import (
    NavigateAction,
    ClickAction,
    FillAction,
    HoverAction,
    SelectAction,
    WaitAction,
    ScrollToAction,
    KeyboardPressAction,
    ScreenshotAction,
)
from stepper.engine.actions.assertions import (
    AssertCountAction,
    AssertTextAction,
    AssertVisibleAction,
    StoreCountAction,
    StoreAction,
)
from stepper.engine.actions.data import (
    ExtractDataAction,
    LoadTestDataAction,
)
from stepper.engine.actions.flow import (
    ForEachItemAction,
    EnsureLoginAction,
    PaginateAction,
    ParallelAction,
    RunWorkflowAction,
)
from stepper.engine.actions.measurement import (
    MeasurePerformanceAction,
    VisualCompareAction,
)

__all__ = [
    # basic
    "NavigateAction", "ClickAction", "FillAction", "HoverAction", "SelectAction",
    "WaitAction", "ScrollToAction", "KeyboardPressAction", "ScreenshotAction",
    # assertions
    "AssertCountAction", "AssertTextAction", "AssertVisibleAction",
    "StoreCountAction", "StoreAction",
    # data
    "ExtractDataAction", "LoadTestDataAction",
    # flow
    "ForEachItemAction", "EnsureLoginAction", "PaginateAction",
    "ParallelAction", "RunWorkflowAction",
    # measurement
    "MeasurePerformanceAction", "VisualCompareAction",
]
