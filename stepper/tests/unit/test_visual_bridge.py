"""
VisualBridge — the pre-flight check that decides whether healing is warranted.

It runs before DOMSnapshotCascade and before any AI call, and answers one
question: is the element actually missing, or is it sitting right there, hidden
or disabled?

That distinction is worth a test because the two cases want opposite
treatment. A genuinely absent element is what the healer is for. An element
that is present but disabled is not a broken selector at all — healing it
produces a "better" selector for the same unclickable button, spends tokens,
and buries the real problem (the form is invalid, the button is waiting on
something) under a successful-looking heal.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.healer import visual_bridge as vb
from stepper.engine.healer.visual_bridge import VisualBridge
from stepper.engine.interfaces import StepConfig


# ── Doubles ───────────────────────────────────────────────────────────────────

def _locator(count: int = 1, visible: bool = True, enabled: bool = True):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.first.is_visible = AsyncMock(return_value=visible)
    loc.first.is_enabled = AsyncMock(return_value=enabled)
    return loc


def _page(locator=None):
    """A page whose every lookup method returns the same locator, and records how."""
    page = MagicMock()
    loc = locator if locator is not None else _locator()
    page.get_by_role.return_value = loc
    page.get_by_label.return_value = loc
    page.get_by_placeholder.return_value = loc
    page.locator.return_value = loc
    return page


@pytest.fixture(autouse=True)
def no_visibility_wait(monkeypatch):
    """
    check() sleeps 2s before deciding an invisible element is really hidden —
    correct in a browser, and 2s of nothing in a unit suite.
    """
    monkeypatch.setattr(vb, "VISIBILITY_WAIT_S", 0)


# ── The four answers ──────────────────────────────────────────────────────────

async def test_a_visible_enabled_element_is_ok():
    page = _page(_locator(count=1, visible=True, enabled=True))

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) == "ok"


async def test_an_element_that_is_not_in_the_dom_returns_none():
    """None means 'not my call' — the cascade takes it from here."""
    page = _page(_locator(count=0))

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) is None


async def test_an_element_present_but_invisible_is_hidden():
    page = _page(_locator(visible=False))

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) == "hidden"


async def test_an_element_visible_but_not_interactive_is_disabled():
    """
    The case worth catching. Healing a disabled button finds a nicer selector
    for a button that still will not click, and reports success.
    """
    page = _page(_locator(visible=True, enabled=False))

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) == "disabled"


async def test_an_element_that_becomes_visible_during_the_wait_is_not_hidden():
    """
    Animations and lazy panels are why the wait exists: invisible now, visible a
    moment later. Calling that hidden would send a perfectly good step to the
    healer on every run.
    """
    loc = _locator()
    loc.first.is_visible = AsyncMock(side_effect=[False, True])
    page = _page(loc)

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) == "ok"
    assert loc.first.is_visible.await_count == 2


# ── Locator selection ─────────────────────────────────────────────────────────

async def test_a_step_with_no_element_is_not_this_check_s_business():
    """navigate, wait, store — nothing to look up, nothing to say."""
    assert await VisualBridge.check(_page(), StepConfig(action="navigate", url="/x")) is None


async def test_an_unrecognised_cfg_shape_returns_none():
    """An xpath-only cfg has no branch here; that is a pass, not a crash."""
    page = _page()

    assert await VisualBridge.check(page, StepConfig(action="click", element={"xpath": "//div"})) is None


@pytest.mark.parametrize(
    "element, method",
    [
        ({"role": "button", "name": "Log in"}, "get_by_role"),
        ({"label": "Username"},                "get_by_label"),
        ({"placeholder": "Search"},            "get_by_placeholder"),
        ({"id": "go"},                         "locator"),
        ({"css": ".btn"},                      "locator"),
    ],
)
async def test_each_cfg_shape_uses_the_matching_playwright_lookup(element, method):
    page = _page()

    await VisualBridge.check(page, StepConfig(action="click", element=element))

    assert getattr(page, method).called, f"{element} should have used {method}"


async def test_semantic_identifiers_are_preferred_over_css():
    """
    Same precedence as the resolver cascade: role+name beats a CSS selector when
    a cfg carries both, because it is the one that survives a redesign.
    """
    page = _page()

    await VisualBridge.check(
        page,
        StepConfig(action="click", element={"role": "button", "name": "Log in", "css": ".btn"}),
    )

    assert page.get_by_role.called
    assert not page.locator.called


async def test_role_without_a_name_falls_through_to_the_next_identifier():
    """`role` alone is not enough for get_by_role — the branch needs both."""
    page = _page()

    await VisualBridge.check(page, StepConfig(action="click", element={"role": "button", "css": ".btn"}))

    assert not page.get_by_role.called
    assert page.locator.called


# ── Failure is not this component's problem ───────────────────────────────────

async def test_a_page_that_throws_returns_none_rather_than_propagating():
    """
    This is a pre-flight optimisation. If it cannot answer, the cascade runs
    anyway — which is the correct, slower behaviour. Raising here would turn a
    recoverable step failure into a crashed run.
    """
    page = MagicMock()
    page.locator.side_effect = RuntimeError("context destroyed")

    assert await VisualBridge.check(page, StepConfig(action="click", element={"id": "go"})) is None
