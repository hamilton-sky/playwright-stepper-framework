"""
The description-driven fallbacks only settle on an element the action can take.

`resolve()` falls back to matching the step's *description* when the cfg names
nothing on the page. Until it knew the action, that fallback could pick any
element whose text shared a word with the description. In CI, on the SauceDemo
fixture, "Type username into the username field" keyword-matched a text node,
and the fill died on

    Element is not an <input>, <textarea>, <select> or [contenteditable]

A click is the dangerous half: a heading reading "Login" is clickable as far as
Playwright is concerned, so "Click the Login button" clicked the heading and the
step reported passed.

The rules themselves run in the browser (resolvers/action_fit.py) and were
checked against Playwright's own fill() on a real page; these tests hold the
wiring — that the fallbacks filter, that the deterministic path does not, and
that every acting caller says what it is about to do.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import StepConfig
from stepper.engine.resolvers import action_fit
from stepper.engine.resolvers.element_resolver import ElementResolver


@pytest.fixture(autouse=True)
def _allow_building_a_resolver(monkeypatch):
    """ElementResolver builds a SemanticResolver; conftest refuses the model load."""
    monkeypatch.setattr(
        "stepper.engine.resolvers.strategies.SemanticResolver.__init__",
        lambda self, *a, **kw: None,
    )


def _candidate(fits: bool) -> MagicMock:
    """A live-element double whose action-fit check answers `fits`."""
    loc = MagicMock()
    loc.evaluate = AsyncMock(return_value=fits)
    return loc


def _resolver(keyword: list, shortlist: list | None = None) -> ElementResolver:
    r = ElementResolver([])
    r._keyword_fuzzy = MagicMock(find=AsyncMock(return_value=keyword))
    r._desc_fallback = MagicMock(find_candidates=AsyncMock(return_value=shortlist or []))
    return r


# ── keyword-fuzzy ─────────────────────────────────────────────────────────────

async def test_a_lone_keyword_match_that_cannot_take_the_fill_is_not_used():
    """The CI case: one text node matched, and it is not a field."""
    text_node = _candidate(fits=False)
    r = _resolver([text_node])

    result = await r.resolve(MagicMock(), {}, "Type username into the username field",
                             action="fill")

    assert result.found is False


async def test_dropping_the_unfit_candidates_can_leave_the_one_that_fits():
    heading, button = _candidate(fits=False), _candidate(fits=True)
    r = _resolver([heading, button])

    result = await r.resolve(MagicMock(), {}, "Click the Login button", action="click")

    assert result.found is True
    assert result.locator is button
    assert result.method == "keyword-fuzzy"


async def test_without_an_action_nothing_is_filtered():
    """Callers that do not say what they will do keep the old behaviour."""
    heading = _candidate(fits=False)
    r = _resolver([heading])

    result = await r.resolve(MagicMock(), {}, "the Login heading")

    assert result.locator is heading
    heading.evaluate.assert_not_awaited()


# ── accessibility-semantic ────────────────────────────────────────────────────

async def test_the_accessibility_shortlist_is_filtered_too():
    link, field = _candidate(fits=False), _candidate(fits=True)
    r = _resolver([], shortlist=[(link, "link Username help", 0.9),
                                 (field, "textbox Username", 0.7)])

    result = await r.resolve(MagicMock(), {}, "Type the username", action="fill")

    assert result.found is True
    assert result.locator is field
    assert result.method == "accessibility-semantic"


async def test_nothing_fitting_is_not_found_rather_than_a_wrong_element():
    r = _resolver([_candidate(fits=False)],
                  shortlist=[(_candidate(fits=False), "heading Login", 0.9)])

    result = await r.resolve(MagicMock(), {}, "Click the Login button", action="click")

    assert result.found is False


# ── the deterministic path is the cfg's to decide ─────────────────────────────

async def test_a_deterministic_match_is_not_second_guessed():
    """The cfg named this element; whether it suits the action is the cfg's problem."""
    named = _candidate(fits=False)
    strategy = MagicMock(priority=60)
    strategy.name = "css"
    strategy.collect = AsyncMock(return_value=[named])
    r = ElementResolver([strategy])

    result = await r.resolve(MagicMock(), {"css": "h1"}, "d", action="click")

    assert result.locator is named
    named.evaluate.assert_not_awaited()


# ── fits() ────────────────────────────────────────────────────────────────────

async def test_an_unreadable_candidate_is_kept():
    """The filter narrows a guess; it does not veto one on missing evidence."""
    loc = MagicMock()
    loc.evaluate = AsyncMock(side_effect=RuntimeError("element is detached"))

    assert await action_fit.fits(loc, "click") is True


async def test_an_unmodelled_action_never_reads_the_page():
    loc = _candidate(fits=False)

    assert await action_fit.fits(loc, "scroll_to") is True
    loc.evaluate.assert_not_awaited()


def test_the_rules_follow_playwright_s_own_retargeting_and_readonly():
    js = action_fit._FIT_JS
    assert "el.control" in js, "fill()/select_option() retarget a <label> to its control"
    assert "aria-readonly" in js and "'textbox'" in js, (
        "aria-readonly counts only on a role that supports it, as Playwright reads it"
    )
    assert "checkVisibility" in js


# ── every acting caller says what it is about to do ───────────────────────────

def _not_found_resolver():
    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=MagicMock(found=False, confidence=0.0, method="not-found")
    )
    return resolver


@pytest.mark.parametrize("action_name", ["click", "fill", "hover", "select"])
async def test_engine_actions_pass_their_action(action_name):
    from stepper.engine.actions.factory import build_default_registry

    resolver = _not_found_resolver()
    step = StepConfig(action=action_name, description="d",
                      element={"css": ".x"}, input_value="v")

    await build_default_registry().create(action_name).execute(
        MagicMock(), step, resolver, None, None
    )

    assert resolver.resolve.await_args.kwargs.get("action") == action_name


@pytest.mark.parametrize("extra", [{"js_click": True}, {"force": True}])
async def test_a_click_that_bypasses_actionability_is_not_filtered(extra):
    """js_click reaches a hidden dropdown button on purpose; the filter would drop it."""
    from stepper.engine.actions.factory import build_default_registry

    resolver = _not_found_resolver()
    step = StepConfig(action="click", description="d", element={"css": ".x"}, extra=extra)

    await build_default_registry().create("click").execute(
        MagicMock(), step, resolver, None, None
    )

    assert resolver.resolve.await_args.kwargs.get("action") is None


async def test_a_page_object_js_click_is_not_filtered():
    from poms.shared.base_page import BasePage
    from poms.shared.locator import Locator

    resolver = _not_found_resolver()
    page = BasePage.__new__(BasePage)
    page._resolver, page._page, page._behaviour = resolver, MagicMock(), None
    page._driver = MagicMock()

    await page._interact(Locator(css=".x", description="d"), "click", js_click=True)

    assert resolver.resolve.await_args.kwargs.get("action") is None


@pytest.mark.parametrize("action_name", ["click", "fill", "hover", "select"])
async def test_extra_strict_makes_an_acting_step_resolve_strictly(action_name):
    """What the heal workflows use, so a broken selector reaches the healer."""
    from stepper.engine.actions.factory import build_default_registry

    resolver = _not_found_resolver()
    step = StepConfig(action=action_name, description="d", element={"css": ".x"},
                      input_value="v", extra={"strict": True})

    await build_default_registry().create(action_name).execute(
        MagicMock(), step, resolver, None, None
    )

    assert resolver.resolve.await_args.kwargs.get("strict") is True


@pytest.mark.parametrize("action", ["fill", "click"])
async def test_page_objects_pass_their_action(action):
    from poms.shared.base_page import BasePage
    from poms.shared.locator import Locator

    resolver = _not_found_resolver()
    page = BasePage.__new__(BasePage)
    page._resolver, page._page, page._behaviour = resolver, MagicMock(), None
    page._driver = MagicMock()

    kwargs = {"value": "v"} if action == "fill" else {}
    await page._interact(Locator(css=".x", description="d"), action, **kwargs)

    assert resolver.resolve.await_args.kwargs.get("action") == action


def test_both_heal_workflows_keep_their_broken_steps_strict():
    """
    Without it the fuzzy fallbacks find the real fields themselves, the steps
    pass unhealed, and the workflows exercise nothing — which is what CI's
    healed-count check exists to catch.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "sites" / "saucedemo" / "workflows"
    for name in ("sd_heal_test", "sd_full_heal_flow"):
        steps = json.loads((root / f"{name}.json").read_text())["steps"]
        broken = [s for s in steps if s.get("heal") and s.get("element")]
        assert len(broken) == 3, name
        assert all((s.get("extra") or {}).get("strict") is True for s in broken), name


# ── review round 1 ────────────────────────────────────────────────────────────

async def test_the_visual_fallback_pick_is_checked_too():
    """The last description-driven guess gets the same check as the others."""
    heading = _candidate(fits=False)
    r = ElementResolver([], use_visual_ai=True)
    r._keyword_fuzzy = MagicMock(find=AsyncMock(return_value=[]))
    r._desc_fallback = MagicMock(find_candidates=AsyncMock(return_value=[]))
    r._visual = MagicMock(collect=AsyncMock(return_value=[(heading, 0.9)]))

    result = await r.resolve(MagicMock(), {}, "Click the Login button", action="click")

    assert result.found is False


async def test_the_visual_fallback_pick_is_kept_when_it_fits():
    button = _candidate(fits=True)
    r = ElementResolver([], use_visual_ai=True)
    r._keyword_fuzzy = MagicMock(find=AsyncMock(return_value=[]))
    r._desc_fallback = MagicMock(find_candidates=AsyncMock(return_value=[]))
    r._visual = MagicMock(collect=AsyncMock(return_value=[(button, 0.9)]))

    result = await r.resolve(MagicMock(), {}, "Click the Login button", action="click")

    assert result.locator is button


def test_visibility_is_read_before_the_label_retarget_as_playwright_does():
    """
    Checked against Playwright's own fill() in a real browser: a visible
    <label> for a hidden input fills, and a hidden <label> for a visible input
    does not — visibility is read on the element handed in, enabledness and
    editability on the control it is retargeted to.
    """
    js = action_fit._FIT_JS
    assert js.index("checkVisibility") < js.index("el = label.control")


def test_anything_inside_a_label_is_retargeted():
    """<label><span>Username</span><input></label>: the span fills the input."""
    assert "el.closest('label')" in action_fit._FIT_JS


def test_a_disabled_control_above_the_match_refuses_it():
    """
    <button disabled style="cursor:pointer"><span>Login</span></button> — the
    inherited pointer cursor must not get the span past the disabled button.
    """
    js = action_fit._FIT_JS
    assert "button:disabled" in js
    assert js.index("button:disabled") < js.index("cursor === 'pointer'")


def test_fill_accepts_the_input_types_playwright_sets():
    """color, range and the date family are filled by value; only these are refused."""
    js = action_fit._FIT_JS
    assert "'color'" not in js and "'range'" not in js
    for refused in ("'checkbox'", "'radio'", "'file'", "'hidden'", "'submit'"):
        assert refused in js
