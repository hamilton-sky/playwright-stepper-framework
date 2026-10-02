"""
DOMSnapshotCascade — the cost ladder the README leans on hardest.

The claim is that healing escalates free → cheap → expensive and stops as soon
as it can, so a broken selector that the embeddings resolve outright costs zero
AI tokens. That claim had no test.

These are unit tests: the page is a stub, and SemanticResolver.score is
monkeypatched so the rung a capture lands on is chosen by the test rather than
by whatever MiniLM happens to think today. What is being locked down is the
*decision*, not the embedding — the thresholds, the uniqueness rule, and what
each rung costs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import StepConfig
from stepper.engine.healer import dom_snapshot as ds
from stepper.engine.healer.dom_snapshot import (
    DOMSnapshotCascade,
    _HIGH_THRESHOLD,
    _LOW_THRESHOLD,
    _TOP_N,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _element(**kw) -> dict:
    """One entry as _ELEMENT_QUERY_JS would return it."""
    base = {
        "tag": "BUTTON", "text": "", "role": "button", "aria": None,
        "id": "", "placeholder": None, "name": None, "type": None,
        "title": None, "value": None,
    }
    base.update(kw)
    return base


def _step(**kw) -> StepConfig:
    base = {
        "action": "click", "description": "click the login button",
        "element": {"css": ".broken"}, "extra": {},
    }
    base.update(kw)
    return StepConfig(**base)


def _rung_step(**kw) -> StepConfig:
    """
    A step for testing the score rungs themselves. Its action is one the
    clear-winner rule does not model, so a lone element is judged on the
    thresholds alone — the rule has its own tests further down.
    """
    return _step(action="scroll_to", **kw)


def _page(elements: list[dict], scoped_html: str = "", walk=None):
    """
    A page stub whose evaluate() dispatches on the JS it is handed, the way the
    real cascade calls it: the element query, the scoped-html lookup, the DOM
    walk.
    """
    page = MagicMock()

    async def evaluate(js, *args):
        if "querySelectorAll" in js:
            return elements
        if "closest" in js:
            return scoped_html
        if "walk" in js:
            return walk
        raise AssertionError(f"unexpected evaluate: {js[:60]}")

    page.evaluate = AsyncMock(side_effect=evaluate)
    return page


@pytest.fixture
def fixed_scores(monkeypatch):
    """
    Drive the cascade with scores the test chooses.

    Takes a dict of {element text or id -> score}; anything unlisted scores 0.0.
    Patching the score function rather than the model keeps these tests free of
    sentence-transformers entirely.
    """
    def apply(mapping: dict[str, float]):
        def score(self, query: str, text: str) -> float:
            for needle, value in mapping.items():
                if needle and needle in text:
                    return value
            return 0.0

        # Inject a stub rather than clearing the cache. Setting _semantic to None
        # would make _get_semantic() construct a real SemanticResolver, whose
        # __init__ loads an embedding model — and with the weights no longer
        # vendored, that means a ~90MB download from the hub in the middle of a
        # unit suite that is supposed to need no network at all.
        monkeypatch.setattr(
            DOMSnapshotCascade, "_semantic",
            SimpleNamespace(score=lambda q, t: score(None, q, t)),
        )
        # Neutralise the cross-encoder: it is a separate model and a separate
        # concern, and it would otherwise reorder what the test just fixed.
        monkeypatch.setattr(
            ds._CrossEncoderReranker, "instance",
            classmethod(lambda cls: SimpleNamespace(rerank=lambda q, top: top)),
        )
    return apply


# ── The zero-token rung ───────────────────────────────────────────────────────

async def test_a_unique_high_scoring_element_costs_no_tokens(fixed_scores):
    """
    The headline claim: one element over 0.85 and nothing else near it means the
    healed cfg is synthesised from the element's own attributes, with no AI call
    and no prompt to pay for.
    """
    fixed_scores({"Log in": 0.93, "Register": 0.20})
    page = _page([
        _element(text="Log in", id="login-btn"),
        _element(text="Register", id="register-btn"),
    ])

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "embed_direct"
    assert payload.token_estimate == 0
    assert payload.content == ""
    assert payload.healed_cfg is not None
    assert payload.healed_cfg["role"] == "button"
    assert payload.healed_cfg["name"] == "Log in"


async def test_the_fast_path_needs_a_unique_winner_not_just_a_high_one(fixed_scores):
    """
    Two elements over the threshold is ambiguity, not confidence. Acting on the
    higher of the two would be a guess dressed up as a resolution, so this rung
    hands the choice to the AI instead — cheaply, as candidates rather than DOM.
    """
    fixed_scores({"Log in": 0.93, "Login": 0.91})
    page = _page([
        _element(text="Log in", id="a"),
        _element(text="Login", id="b"),
    ])

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "embed_candidates"
    assert payload.healed_cfg is None, "ambiguous matches must not auto-heal"
    assert payload.token_estimate > 0

    candidates = json.loads(payload.content)["candidates"]
    assert len(candidates) == 2
    assert all("_score" in c for c in candidates)


# ── The middle rung ───────────────────────────────────────────────────────────

async def test_a_middling_score_sends_scoped_dom_not_the_whole_page(fixed_scores):
    """Between 0.50 and 0.85: the AI gets the best guess plus its enclosing form."""
    fixed_scores({"Submit": 0.70})
    page = _page([_element(text="Submit", id="submit")],
                 scoped_html="<form><button id='submit'>Submit</button></form>")

    payload = await DOMSnapshotCascade.capture(page, _rung_step())

    assert payload.strategy_used == "scoped"
    assert payload.healed_cfg is None

    content = json.loads(payload.content)
    assert content["best_match_score"] == 0.7
    assert "<form>" in content["scoped_html"]


async def test_scoped_dom_survives_an_element_with_nothing_to_scope_to(fixed_scores):
    """
    _scoped_html needs an id or aria-label to build a selector from. Without one
    it returns "" — the rung must still produce a usable payload rather than
    falling over or silently dropping to the expensive one.
    """
    fixed_scores({"Submit": 0.70})
    page = _page([_element(text="Submit", id="", aria=None)])

    payload = await DOMSnapshotCascade.capture(page, _rung_step())

    assert payload.strategy_used == "scoped"
    assert "scoped_html" not in json.loads(payload.content)


# ── The expensive rung ────────────────────────────────────────────────────────

async def test_nothing_scoring_above_the_floor_falls_back_to_an_aria_walk(fixed_scores):
    """Below 0.50 the embeddings have nothing to offer, so the AI gets the tree."""
    fixed_scores({"Log in": 0.20})
    page = _page(
        [_element(text="Log in", id="x")],
        walk={"tag": "body", "children": [{"tag": "button", "text": "Log in"}]},
    )

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "aria"
    assert payload.healed_cfg is None
    assert "Log in" in payload.content


async def test_a_page_with_no_interactive_elements_goes_straight_to_aria(fixed_scores):
    fixed_scores({})
    page = _page([], walk={"tag": "body", "children": []})

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "aria"


async def test_a_page_that_will_not_evaluate_still_returns_a_payload():
    """
    page.evaluate throwing is a normal condition — a navigation mid-capture, a
    closed context. The healer must get a DomPayload back either way; raising
    here would turn a heal attempt into a crash.
    """
    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=RuntimeError("execution context destroyed"))

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "aria"
    assert payload.content == ""


# ── The ladder as a whole ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "top_score, expected",
    [
        (0.99, "embed_direct"),
        (_HIGH_THRESHOLD, "embed_direct"),      # inclusive at the top boundary
        (_HIGH_THRESHOLD - 0.01, "scoped"),
        (_LOW_THRESHOLD, "scoped"),             # inclusive at the low boundary
        (_LOW_THRESHOLD - 0.01, "aria"),
        (0.0, "aria"),
    ],
)
async def test_each_threshold_selects_its_rung(fixed_scores, top_score, expected):
    """Both thresholds are inclusive; the rungs are contiguous with no gap."""
    fixed_scores({"Target": top_score})
    page = _page([_element(text="Target", id="t")], walk={"tag": "body"})

    payload = await DOMSnapshotCascade.capture(page, _rung_step())

    assert payload.strategy_used == expected


async def test_the_cheap_rungs_have_a_ceiling_and_the_expensive_one_does_not(fixed_scores):
    """
    The property that makes the cascade worth having is not that each rung is
    dearer than the last — on a small enough page an ARIA walk can undercut a
    scoped form, and that is fine. It is that the cheap rungs are *bounded*:
    their cost is set by the shortlist, not by how big the page is, so a
    thousand-element page heals for the same price as a ten-element one. Only
    the last rung pays for the page.

    A change that let page size leak into embed_candidates would keep every
    threshold test above green and quietly delete the reason to escalate at all.
    """
    def page_of(n: int):
        elements = [_element(text=f"Item {i}", id=f"i{i}") for i in range(n)]
        walk = {
            "tag": "body",
            "children": [{"tag": "button", "text": f"Item {i}", "id": f"i{i}"}
                         for i in range(n)],
        }
        return elements, walk

    async def cost(n: int, score: float) -> tuple[str, int]:
        elements, walk = page_of(n)
        fixed_scores({"Item": score})
        payload = await DOMSnapshotCascade.capture(_page(elements, walk=walk), _step())
        return payload.strategy_used, payload.token_estimate

    small_strategy, small_candidates = await cost(5, 0.90)
    large_strategy, large_candidates = await cost(500, 0.90)
    assert small_strategy == large_strategy == "embed_candidates"
    assert small_candidates == large_candidates, (
        "embed_candidates cost moved with page size — the shortlist is not capping it"
    )

    _, small_aria = await cost(5, 0.10)
    _, large_aria = await cost(500, 0.10)
    assert large_aria > small_aria * 10, (
        "the ARIA rung is meant to be the one that pays for the page"
    )

    # And the floor is free, on any page at all.
    fixed_scores({"Only": 0.95})
    payload = await DOMSnapshotCascade.capture(
        _page([_element(text="Only", id="only")]), _step()
    )
    assert payload.strategy_used == "embed_direct"
    assert payload.token_estimate == 0


async def test_only_the_top_candidates_are_ever_sent(fixed_scores):
    """
    Twenty elements over the threshold must not become a twenty-element prompt —
    the shortlist is what keeps the ambiguous rung cheap.
    """
    fixed_scores({"Item": 0.90})
    page = _page([_element(text=f"Item {i}", id=f"i{i}") for i in range(20)])

    payload = await DOMSnapshotCascade.capture(page, _step())

    assert payload.strategy_used == "embed_candidates"
    assert len(json.loads(payload.content)["candidates"]) == _TOP_N


# ── Cfg synthesis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "element, expected",
    [
        (_element(role="button", text="Save", aria=None), {"role": "button", "name": "Save"}),
        (_element(role="button", aria="Close dialog"), {"role": "button", "name": "Close dialog"}),
        (_element(role="", aria="Close dialog"), {"label": "Close dialog"}),
        (_element(role="", placeholder="Username"), {"placeholder": "Username"}),
        (_element(role="", text="Plain text"), {"text": "Plain text"}),
        (_element(role="", id="only-an-id"), {"id": "only-an-id"}),
        (_element(role="", tag="INPUT"), {"css": "input"}),
    ],
)
def test_a_healed_cfg_prefers_the_most_durable_identifier(element, expected):
    """
    role+name first, css last — the same resilience order the resolver cascade
    uses. A heal that emits `{"css": "div"}` when the element had an aria-label
    has produced a selector that will break again next sprint.
    """
    cfg = DOMSnapshotCascade._element_to_cfg(element)

    for key, value in expected.items():
        assert cfg[key] == value


def test_an_aria_label_outranks_visible_text_for_the_accessible_name():
    """Icon buttons have an aria-label and junk text; the label is the real name."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(role="button", aria="Close dialog", text="✕")
    )

    assert cfg["name"] == "Close dialog"


# ── Query construction ────────────────────────────────────────────────────────

def test_the_query_is_built_from_the_description_and_the_step_params():
    query = DOMSnapshotCascade._build_query(
        _step(description="fill the search box", extra={"query": "Dune"})
    )

    assert "fill the search box" in query
    assert "Dune" in query


def test_a_thin_description_is_padded_from_the_action_name():
    """
    A step described as "go" gives the embeddings nothing to work with. The
    action name is not much, but it is more than three characters.
    """
    query = DOMSnapshotCascade._build_query(
        _step(action="add_to_cart", description="go", extra={})
    )

    assert len(query) > len("go")
    assert "cart" in query


# ── The clear-winner rule ─────────────────────────────────────────────────────
#
# Measured on the SauceDemo login fixture, MiniLM put the right element first for
# every heal step but never at ≥ 0.85: username 0.790 (runner-up 0.341), password
# 0.755 (0.382), Login 0.728 (alone among clickables). Every heal fell to the
# scoped rung and needed an AI pick. The rule: a candidate that suits the action
# and clearly leads the other suitable candidates is healed directly.

from stepper.engine.healer.dom_snapshot import _LONE_MIN, _MARGIN  # noqa: E402


def _login_form():
    return [
        _element(tag="INPUT", role="input", placeholder="Username", name="user-name",
                 id="user-name", type="text"),
        _element(tag="INPUT", role="input", placeholder="Password", name="password",
                 id="password", type="password"),
        _element(tag="INPUT", role="input", name="login-button", id="login-button",
                 type="submit", value="Login"),
    ]


async def test_the_measured_login_form_heals_with_no_ai_call(fixed_scores):
    """The numbers from the fixture: a 0.79 leading by 0.45 is not ambiguous."""
    fixed_scores({"Username": 0.79, "Login": 0.34, "Password": 0.25})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()),
        _step(action="fill", description="Type username into the username field"),
    )

    assert payload.strategy_used == "embed_direct"
    assert payload.healed_cfg["placeholder"] == "Username"
    assert payload.token_estimate == 0


async def test_a_fill_never_heals_onto_a_button(fixed_scores):
    """
    The submit button outscoring every field is not a reason to type into it. Only
    elements that take text are candidates for a fill, so the answer stays with
    the AI rather than becoming a confident wrong one.
    """
    fixed_scores({"Login": 0.80, "Username": 0.40, "Password": 0.38})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form(), walk={"tag": "body"}),
        _step(action="fill", description="type into the login field"),
    )

    assert payload.strategy_used != "embed_direct"


async def test_a_click_ignores_text_fields_and_heals_to_the_lone_button(fixed_scores):
    """Text inputs are not clickable targets; the submit input is the one candidate."""
    fixed_scores({"Login": 0.73, "Username": 0.30, "Password": 0.42})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()),
        _step(action="click", description="Click the Login button to submit credentials"),
    )

    assert payload.strategy_used == "embed_direct"
    # Its value is its accessible name — the most durable identifier it has.
    assert payload.healed_cfg == {"priority": 0, "role": "button", "name": "Login"}


@pytest.mark.parametrize("lead, expected", [
    (_MARGIN, "embed_direct"),            # inclusive
    (_MARGIN - 0.01, "scoped"),
])
async def test_the_lead_must_reach_the_margin(fixed_scores, lead, expected):
    fixed_scores({"Username": 0.70, "Password": round(0.70 - lead, 4)})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()[:2]),
        _step(action="fill", description="type the username"),
    )

    assert payload.strategy_used == expected


async def test_a_clear_lead_still_needs_the_floor(fixed_scores):
    """0.45 over 0.10 leads by plenty, and is still a weak match for anything."""
    fixed_scores({"Username": 0.45, "Password": 0.10})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()[:2], walk={"tag": "body"}),
        _step(action="fill", description="type the username"),
    )

    assert payload.strategy_used == "aria"


@pytest.mark.parametrize("score, expected", [
    (_LONE_MIN, "embed_direct"),
    (_LONE_MIN - 0.01, "scoped"),
])
async def test_a_lone_candidate_has_to_clear_a_higher_bar(fixed_scores, score, expected):
    """
    With nothing to lead, the margin is the score itself — the case where the
    target is gone and something unrelated is left. So it needs more than the
    0.50 floor a contested winner does.
    """
    fixed_scores({"Accept": score})

    payload = await DOMSnapshotCascade.capture(
        _page([_element(text="Accept", id="accept")]),
        _step(action="click", description="click the login button"),
    )

    assert payload.strategy_used == expected


async def test_the_cross_encoder_can_veto_the_winner(fixed_scores, monkeypatch):
    """If the re-ranker prefers a different suitable element, the AI decides."""
    fixed_scores({"Username": 0.79, "Password": 0.30})
    monkeypatch.setattr(
        ds._CrossEncoderReranker, "instance",
        classmethod(lambda cls: SimpleNamespace(rerank=lambda q, top: list(reversed(top)))),
    )

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()[:2], scoped_html="<form></form>"),
        _step(action="fill", description="type the username"),
    )

    assert payload.strategy_used != "embed_direct"


async def test_an_action_the_rule_does_not_model_is_unaffected(fixed_scores):
    fixed_scores({"Username": 0.79, "Password": 0.20})

    payload = await DOMSnapshotCascade.capture(
        _page(_login_form()[:2], scoped_html="<form></form>"),
        _step(action="scroll_to", description="scroll to the username"),
    )

    assert payload.strategy_used == "scoped"


@pytest.mark.parametrize("action, element, fits", [
    ("fill",  _element(tag="INPUT", type="text"), True),
    ("fill",  _element(tag="INPUT", type="password"), True),
    ("fill",  _element(tag="INPUT", type=None), True),          # type defaults to text
    ("fill",  _element(tag="INPUT", type="submit"), False),
    ("fill",  _element(tag="INPUT", type="checkbox"), False),
    ("fill",  _element(tag="TEXTAREA", role="textarea"), True),
    ("fill",  _element(tag="DIV", role="textbox"), False),      # a role is not editability
    ("fill",  _element(tag="DIV", role="textbox", editable=True), True),
    ("fill",  _element(tag="BUTTON", role="combobox"), False),
    ("fill",  _element(tag="INPUT", type="text", readonly=True), False),
    ("fill",  _element(tag="BUTTON", role="button"), False),
    ("click", _element(tag="BUTTON", role="button"), True),
    ("click", _element(tag="A", role="a"), True),
    ("click", _element(tag="INPUT", type="submit"), True),
    ("click", _element(tag="INPUT", type="text"), False),
    ("click", _element(tag="DIV", role="link"), True),
    ("select", _element(tag="SELECT", role="select"), True),
    ("select", _element(tag="DIV", role="listbox"), False),      # select_option needs <select>
    ("select", _element(tag="BUTTON", role="combobox"), False),
    ("select", _element(tag="BUTTON", role="button"), False),
    ("scroll_to", _element(tag="BUTTON", role="button"), None),
])
def test_which_elements_suit_which_action(action, element, fits):
    assert DOMSnapshotCascade._fits_action(action, element) is fits


# ── Roles a healed cfg can actually resolve ───────────────────────────────────
#
# _ELEMENT_QUERY_JS falls back to the lower-cased tag when an element has no role
# attribute. "a", "select" and "input" are not ARIA roles, so a healed
# {"role": "select"} resolved to nothing. Found in review of the clear-winner rule,
# which made those direct heals reachable; the ≥ 0.85 rung had the same hole.

@pytest.mark.parametrize("element, role", [
    (_element(tag="A", role="a", text="Home", href=True), "link"),
    (_element(tag="A", role="a", text="Cart", href=False), ""),   # no href, no link role
    (_element(tag="BUTTON", role="button", text="Save"), "button"),
    (_element(tag="SELECT", role="select"), "combobox"),
    (_element(tag="SELECT", role="select", multirow=True), "listbox"),
    (_element(tag="TEXTAREA", role="textarea"), "textbox"),
    (_element(tag="INPUT", role="input", type="text"), "textbox"),
    (_element(tag="INPUT", role="input", type=None), "textbox"),
    (_element(tag="INPUT", role="input", type="submit"), "button"),
    (_element(tag="INPUT", role="input", type="checkbox"), "checkbox"),
    (_element(tag="INPUT", role="input", type="email"), "textbox"),
    (_element(tag="INPUT", role="input", type="number"), "spinbutton"),
    (_element(tag="INPUT", role="input", type="search"), "searchbox"),
    (_element(tag="INPUT", role="input", type="range"), "slider"),
    (_element(tag="INPUT", role="input", type="password"), ""),   # no implicit role
    (_element(tag="INPUT", role="input", type="date"), ""),
    (_element(tag="DIV", role="div"), ""),                       # no implicit role
    (_element(tag="DIV", role="tab"), "tab"),                    # explicit attribute kept
    (_element(tag="A", role="button"), "button"),
])
def test_tag_derived_roles_become_aria_roles(element, role):
    assert DOMSnapshotCascade._aria_role(element) == role


def test_a_select_is_not_named_after_its_options():
    """Its textContent is every option at once — never a usable accessible name."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="SELECT", role="select", text="Name (A to Z) Name (Z to A)",
                 id="sort")
    )

    assert cfg.get("role") is None
    assert "Name (A to Z)" not in json.dumps(cfg)
    assert cfg["id"] == "sort"


def test_a_select_with_a_label_resolves_as_a_combobox():
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="SELECT", role="select", aria="Sort by", text="A B C")
    )

    assert cfg["role"] == "combobox"
    assert cfg["name"] == "Sort by"


# ── Only actionable elements can be clear winners ─────────────────────────────

@pytest.mark.parametrize("state", [{"hidden": True}, {"disabled": True}])
def test_a_hidden_or_disabled_element_suits_no_action(state):
    """
    A closed menu's links are in the DOM but not on screen; Playwright's
    actionability checks would refuse the healed click and spend the timeout.
    """
    el = _element(tag="BUTTON", role="button", **state)

    for action in ("fill", "click", "hover", "select"):
        assert DOMSnapshotCascade._fits_action(action, el) is False


async def test_a_lone_hidden_button_is_not_healed_to(fixed_scores):
    fixed_scores({"Logout": 0.90 - 0.10})
    page = _page([_element(text="Logout", id="logout", hidden=True)],
                 scoped_html="<nav></nav>")

    payload = await DOMSnapshotCascade.capture(
        page, _step(action="click", description="click logout")
    )

    assert payload.strategy_used != "embed_direct"


def test_a_password_field_heals_to_its_placeholder_not_a_role():
    """A password input has no implicit ARIA role; get_by_role('textbox') misses it."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="INPUT", role="input", type="password", aria="Password",
                 placeholder="Password")
    )

    assert cfg.get("role") is None
    assert cfg == {"priority": 0, "label": "Password"}


def test_a_submit_input_is_named_by_its_value():
    """An <input type=submit> has no textContent; without this it healed to {"css": "input"}."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="INPUT", role="input", type="submit", value="Login", id="")
    )

    assert cfg == {"priority": 0, "role": "button", "name": "Login"}


def test_an_anchor_without_href_is_not_healed_to_a_link_role():
    """SauceDemo's cart link is an <a> with a click handler and no href — no link role."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="A", role="a", text="Cart", href=False, id="cart")
    )

    assert cfg.get("role") is None
    assert cfg == {"priority": 0, "text": "Cart"}


async def test_the_veto_reaches_a_winner_below_the_pagewide_top_n(fixed_scores, monkeypatch):
    """
    Five unsuitable elements outscoring the winner filled the page-wide re-rank,
    so the winner was never re-ranked and the veto passed by default. The
    compatible shortlist is re-ranked itself now.
    """
    links = [_element(tag="A", role="a", text=f"Docs {i}", href=True) for i in range(_TOP_N)]
    fixed_scores({**{f"Docs {i}": 0.80 for i in range(_TOP_N)},
                  "Username": 0.75, "Password": 0.20})
    monkeypatch.setattr(
        ds._CrossEncoderReranker, "instance",
        classmethod(lambda cls: SimpleNamespace(rerank=lambda q, top: list(reversed(top)))),
    )

    payload = await DOMSnapshotCascade.capture(
        _page(links + _login_form()[:2], scoped_html="<form></form>"),
        _step(action="fill", description="type the username"),
    )

    assert payload.strategy_used != "embed_direct"


# ── Every healed cfg carries a browser-computed unique selector ───────────────
#
# Review kept finding gaps in the role/name synthesis — a select's role, an
# input's per-type role, a datalist, inputs known only by name. Each gap was a
# heal the resolver could not find. _ELEMENT_QUERY_JS now has the browser compute
# a selector that matches the element and nothing else, and every cfg carries it:
# the semantic identifier is still tried first, and this is the deterministic
# fallback when it does not resolve.

def test_the_unique_selector_rides_along_with_the_semantic_identifier():
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="INPUT", role="input", type="text", placeholder="Username",
                 selector="#user-name")
    )

    assert cfg == {"priority": 0, "placeholder": "Username", "css": "#user-name"}


def test_an_input_known_only_by_name_heals_to_its_selector_not_the_bare_tag():
    """Was {"css": "input"} — every input on the form."""
    cfg = DOMSnapshotCascade._element_to_cfg(
        _element(tag="INPUT", role="input", type="text", name="username",
                 selector='input[name="username"]')
    )

    assert cfg == {"priority": 0, "css": 'input[name="username"]'}


def test_without_a_selector_the_bare_tag_is_still_the_last_resort():
    cfg = DOMSnapshotCascade._element_to_cfg(_element(tag="INPUT", role="", text=""))

    assert cfg == {"priority": 0, "css": "input"}


@pytest.mark.parametrize("typ", ["text", "search", "email"])
def test_a_datalist_input_is_a_combobox(typ):
    el = _element(tag="INPUT", role="input", type=typ, list=True)

    assert DOMSnapshotCascade._aria_role(el) == "combobox"


def test_the_capture_script_computes_the_selector_in_the_browser():
    """The selector is built from the live DOM, so it is unique at capture time."""
    js = ds._ELEMENT_QUERY_JS
    assert "selector:" in js
    # Unique is not enough — an intermediate `body > input` path can be unique and
    # still be another element. The match must be the element itself.
    assert "m.length === 1 && m[0] === el" in js
    assert "CSS.escape" in js


# ── Covered targets, and a semantic identifier that names another element ────

def test_a_covered_element_is_no_click_or_hover_target():
    """An overlay on top means Playwright's click waits for events that never come."""
    el = _element(tag="BUTTON", role="button", covered=True)

    assert DOMSnapshotCascade._fits_action("click", el) is False
    assert DOMSnapshotCascade._fits_action("hover", el) is False


def _locator(count: int, same: bool):
    loc = MagicMock()
    loc.count = AsyncMock(return_value=count)
    loc.evaluate = AsyncMock(return_value=same)
    return loc


@pytest.mark.parametrize("count, same, keeps_semantic", [
    (1, True, True),      # resolves uniquely, to the chosen element
    (1, False, False),    # resolves uniquely — to a different element
    (2, True, False),     # ambiguous
    (0, False, False),    # resolves to nothing
])
async def test_a_direct_heal_keeps_its_semantic_identifier_only_if_it_pins_the_target(
    count, same, keeps_semantic
):
    page = MagicMock()
    page.get_by_role = MagicMock(return_value=_locator(count, same))
    cfg = {"priority": 0, "role": "button", "name": "Delete", "css": "#a"}

    out = await DOMSnapshotCascade._pinned_cfg(page, cfg)

    if keeps_semantic:
        assert out == cfg
    else:
        assert out == {"priority": 0, "css": "#a"}
    page.get_by_role.assert_called_once_with("button", name="Delete", exact=True)


async def test_a_failed_semantic_check_pins_the_selector():
    page = MagicMock()
    page.get_by_placeholder = MagicMock(side_effect=RuntimeError("context destroyed"))

    out = await DOMSnapshotCascade._pinned_cfg(
        page, {"priority": 0, "placeholder": "Username", "css": "#user-name"}
    )

    assert out == {"priority": 0, "css": "#user-name"}


async def test_without_a_pinned_selector_the_cfg_is_left_alone():
    page = MagicMock()
    cfg = {"priority": 0, "placeholder": "Username"}

    assert await DOMSnapshotCascade._pinned_cfg(page, cfg) is cfg
    page.get_by_placeholder.assert_not_called()
