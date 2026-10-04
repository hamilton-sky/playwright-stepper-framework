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


def _keyword_find(candidates: list):
    """A find() double that honours `keep`, as the real one does."""
    async def find(page, description, keep=None):
        if keep is None:
            return list(candidates)
        return [c for c in candidates if await keep(c)]
    return find


def _resolver(keyword: list, shortlist: list | None = None) -> ElementResolver:
    r = ElementResolver([])
    r._keyword_fuzzy = MagicMock(find=_keyword_find(keyword))
    r._desc_fallback = MagicMock(find_candidates=_shortlist_find(shortlist or []))
    return r


def _shortlist_find(shortlist: list):
    """A find_candidates() double that honours `keep`, as the real one does."""
    async def find_candidates(page, description, keep=None):
        if keep is None:
            return list(shortlist)
        return [c for c in shortlist if await keep(c[0])]
    return find_candidates


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


@pytest.mark.parametrize("extra, fit", [({"js_click": True}, "click_js"),
                                        ({"force": True}, "click_force")])
async def test_a_forced_click_says_which_checks_it_skips(extra, fit):
    """
    js_click reaches a hidden dropdown button; a force click skips the enabled
    checks but still needs a box. Both still need something clickable.
    """
    from stepper.engine.actions.factory import build_default_registry

    resolver = _not_found_resolver()
    step = StepConfig(action="click", description="d", element={"css": ".x"}, extra=extra)

    await build_default_registry().create("click").execute(
        MagicMock(), step, resolver, None, None
    )

    assert resolver.resolve.await_args.kwargs.get("action") == fit


async def test_a_page_object_js_click_resolves_as_click_js():
    from poms.shared.base_page import BasePage
    from poms.shared.locator import Locator

    resolver = _not_found_resolver()
    page = BasePage.__new__(BasePage)
    page._resolver, page._page, page._behaviour = resolver, MagicMock(), None
    page._driver = MagicMock()

    await page._interact(Locator(css=".x", description="d"), "click", js_click=True)

    assert resolver.resolve.await_args.kwargs.get("action") == "click_js"


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
    import re
    refused = re.search(r"const notText = \[([^\]]*)\]", action_fit._FIT_JS).group(1)
    assert "'color'" not in refused and "'range'" not in refused
    for t in ("'checkbox'", "'radio'", "'file'", "'hidden'", "'submit'"):
        assert t in refused


async def test_a_click_accepts_every_role_the_accessibility_fallback_offers():
    """
    The fallback can return a custom slider or listbox; a click must not then
    reject it for having the default cursor. One list, passed in, so the two
    cannot drift.
    """
    from stepper.engine.resolvers.strategies import DescriptionFallbackResolver

    loc = _candidate(fits=True)
    await action_fit.fits(loc, "click")

    _, (action, roles) = loc.evaluate.await_args.args
    assert action == "click"
    assert set(roles) == set(DescriptionFallbackResolver.INTERACTIVE_ROLES)



async def test_the_fit_check_runs_before_same_text_deduplication():
    """
    <h1>Login</h1> ahead of <div onclick>Login</div>: find() keeps one element
    per distinct text, so filtering afterwards kept the heading, rejected it,
    and had nothing left. Filtering first keeps the div.
    """
    from stepper.engine.resolvers.strategies import KeywordFuzzyResolver

    def _match(text, fits_click):
        m = MagicMock()
        m.inner_text = AsyncMock(return_value=text)
        m.evaluate = AsyncMock(return_value=fits_click)
        return m

    heading, div = _match("Login", False), _match("Login", True)
    matches = MagicMock()
    matches.count = AsyncMock(return_value=2)
    matches.nth = lambda i: [heading, div][i]
    page = MagicMock()
    page.get_by_text = MagicMock(return_value=matches)

    found = await KeywordFuzzyResolver().find(
        page, "Login", keep=lambda loc: action_fit.fits(loc, "click")
    )

    assert found == [div]



# ── review round 5 ────────────────────────────────────────────────────────────

def test_a_forced_click_still_needs_something_clickable():
    """Visibility and disabled state are skipped; the click-shape walk is not."""
    js = action_fit._FIT_JS
    assert {"click_js", "click_force"} <= action_fit.MODELLED_ACTIONS
    assert "action === 'click' || forced" in js
    assert "action !== 'click_js' && (!box.width || !box.height" in js, (
        "only js_click may skip visibility; a force click still needs a box"
    )


def test_a_property_assigned_onclick_counts_as_clickable():
    """el.onclick = handler sets no [onclick] attribute."""
    assert "typeof n.onclick === 'function'" in action_fit._FIT_JS


def test_a_label_for_a_disabled_control_refuses_a_click():
    """<fieldset disabled><label><span>Login</span><input></label>: activates nothing."""
    assert "label.control.matches(':disabled')" in action_fit._FIT_JS


async def test_the_accessibility_fit_check_runs_before_the_top_k_cut():
    """
    Three links scoring just above the textbox a fill wants filled the top-3,
    were all rejected, and left nothing. Filtering first keeps the textbox.
    """
    from stepper.engine.resolvers.strategies import DescriptionFallbackResolver

    nodes = [{"role": "link", "name": f"Username help {i}"} for i in range(3)]
    nodes.append({"role": "textbox", "name": "Username"})
    locs = {n["name"]: _candidate(fits=n["role"] == "textbox") for n in nodes}

    fb = DescriptionFallbackResolver.__new__(DescriptionFallbackResolver)
    fb._semantic = MagicMock(score=lambda q, d: 0.9 if "link" in d else 0.8)
    fb._node_to_locator = AsyncMock(side_effect=lambda page, n: locs[n["name"]])
    page = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"role": "root", "children": nodes})

    shortlist = await fb.find_candidates(
        page, "Type the username", keep=lambda loc: action_fit.fits(loc, "fill")
    )

    assert [c[0] for c in shortlist] == [locs["Username"]]



async def test_a_fit_check_walks_past_the_node_cap():
    """30 links ahead of the textbox a fill wants: the cap must not cut it off."""
    from stepper.engine.resolvers.strategies import DescriptionFallbackResolver

    nodes = [{"role": "link", "name": f"Help {i}"} for i in range(40)]
    nodes.append({"role": "textbox", "name": "Username"})
    locs = {n["name"]: _candidate(fits=n["role"] == "textbox") for n in nodes}

    fb = DescriptionFallbackResolver.__new__(DescriptionFallbackResolver)
    fb._semantic = MagicMock(score=lambda q, d: 0.9)
    fb._node_to_locator = AsyncMock(side_effect=lambda page, n: locs[n["name"]])
    page = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"role": "root", "children": nodes})

    shortlist = await fb.find_candidates(
        page, "Type the username", keep=lambda loc: action_fit.fits(loc, "fill")
    )

    assert [c[0] for c in shortlist] == [locs["Username"]]



def test_visible_means_a_non_empty_box_as_playwright_reads_it():
    """
    Checked in a real browser: a zero-size button passes checkVisibility() but
    Playwright's is_visible() is False and its click times out.
    """
    js = action_fit._FIT_JS
    assert "!box.width || !box.height" in js
    assert js.index("!box.width") < js.index("el = label.control")



async def test_a_page_object_js_click_does_not_scroll_first():
    """
    A display:none target has no box: scroll_into_view_if_needed() times out
    and the JS click never runs. _resolve_and_click already skipped it.
    """
    from poms.shared.base_page import BasePage
    from poms.shared.locator import Locator

    el = MagicMock()
    el.scroll_into_view_if_needed = AsyncMock(side_effect=TimeoutError("no box"))
    el.evaluate = AsyncMock()
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=MagicMock(
        found=True, confidence=0.95, method="css", locator=MagicMock(first=el)))
    page = BasePage.__new__(BasePage)
    page._resolver, page._page, page._behaviour = resolver, MagicMock(), None
    page._driver = MagicMock()

    acted = await page._interact(Locator(css=".menu", description="d"), "click", js_click=True)

    assert acted is True
    el.scroll_into_view_if_needed.assert_not_awaited()
    el.evaluate.assert_awaited_once()



def test_a_forced_click_never_accepts_a_native_disabled_control():
    """
    Checked in a real browser: el.click() and click(force=True) both return
    normally on <button disabled> and fire nothing — a step that reports
    passed. On aria-disabled the page's handler does run, so only an ordinary
    click turns that away.
    """
    js = action_fit._FIT_JS
    assert "if (nativeDisabled) return false;" in js
    assert "if (!forced && ariaDisabled(el)) return false;" in js



def test_role_is_read_as_a_fallback_list():
    """
    Checked against Playwright's get_by_role on a real page: role="unknown
    button" is a button, role="switch checkbox" a switch, role="presentation
    button" presentation, and role="BUTTON" nothing.
    """
    js = action_fit._FIT_JS
    assert ".split(/\\s+/)" in js and ".find(t => ARIA.has(t))" in js
    assert "widgetRoles.includes(roleOf(n))" in js
    assert "roRoles.includes(roleOf(el))" in js
    assert "toLowerCase().split" not in js



def test_an_orphan_label_is_not_clickable():
    """<label for="missing">: activates nothing, so a click on it would pass vacuously."""
    js = action_fit._FIT_JS
    assert "n.tagName === 'LABEL' && n.control" in js
    assert "summary, label," not in js



def test_aria_disabled_counts_only_on_a_role_that_supports_it():
    """
    Mirrors Playwright's getAriaDisabled, checked on a real page:
    <div aria-disabled onclick> (no role) clicks and fires; a <button> inside
    <div aria-disabled> and a role=button aria-disabled div are refused.
    """
    js = action_fit._FIT_JS
    assert "ARIA_DISABLED_ROLES.has(roleOf(target) || implicitRole(target))" in js
    assert "closest('button, [role=button], a, [role=link]')" in js
    assert "if (v === 'false') return false;" in js
