"""
brightsky-verify acceptance: mapping.map_version, mapping.url_matches and
targets.target_from_element.

Source: spec.md, the bar ("the step mapping for each target kind"), Happy path
step 3, the "Heal and propose" story, the Edge cases table and Interfaces.
"""
from __future__ import annotations

import pytest

from bs_harness import has, pilot_steps, workflow_detail


def _map(steps=None, **kw):
    from stepper.brightsky.mapping import map_version

    return map_version(workflow_detail(steps, **kw))


def _acting(mapped):
    return [s for s in mapped.steps if s.action in ("click", "fill")]


def _step_for(mapped, number):
    """The acting StepConfig that maps BrightSky step `number`."""
    found = [s for s in _acting(mapped) if mapped.step_numbers.get(s.description) == number]
    assert len(found) == 1, f"expected one acting step for BrightSky step {number}"
    return found[0]


def _target(role=None, name=None, selectors=()):
    target = {"selectors": list(selectors), "score": 0.8, "grounding": "current_page"}
    if role is not None:
        target["role"] = role
    if name is not None:
        target["accessibleName"] = name
    return target


# Happy path 3: The mapping turns the three steps into stepper steps: a
# `navigate` to `https://openlibrary.org/`; `fill` of the textbox "Search" with
# "The Hobbit" and press Enter; `click` of the link "The Hobbit"; `click` of the
# link "J.R.R. Tolkien".
def test_the_pilot_maps_to_navigate_fill_click_click():
    mapped = _map()

    assert [s.action for s in mapped.steps] == ["navigate", "fill", "click", "click"]
    navigate = mapped.steps[0]
    assert "https://openlibrary.org/" in (navigate.url, navigate.input_value)


def test_the_pilot_fill_types_the_quoted_value_into_the_search_textbox():
    mapped = _map()
    fill = _step_for(mapped, 1)

    assert fill.action == "fill"
    assert fill.input_value == "The Hobbit"
    assert fill.element.get("role") == "textbox"
    assert has(fill.element, "Search")


def test_the_pilot_clicks_map_role_and_accessible_name():
    mapped = _map()
    hobbit, tolkien = _step_for(mapped, 2), _step_for(mapped, 3)

    assert hobbit.action == "click" and tolkien.action == "click"
    assert hobbit.element.get("role") == "link" and has(hobbit.element, "The Hobbit")
    assert tolkien.element.get("role") == "link" and has(tolkien.element, "J.R.R. Tolkien")


# Interfaces: `step_numbers: dict[str, int]` (step description → BrightSky step number)
def test_step_numbers_name_each_brightsky_step_once():
    mapped = _map()

    assert sorted(mapped.step_numbers[s.description] for s in _acting(mapped)) == [1, 2, 3]


# Story: Every acting step `map_version` returns (`click`, `fill`) has
#        `extra["strict"] is True`.
def test_every_acting_step_is_strict():
    mapped = _map()

    assert len(_acting(mapped)) == 3
    assert all(s.extra.get("strict") is True for s in _acting(mapped))


# Bar: the step mapping for each target kind.
@pytest.mark.parametrize("selector", [
    "#search-results-first",
    ".searchResultItem a.results",
    "//a[@data-test='book-title']",
])
def test_a_selector_only_target_maps_to_that_selector_and_no_role(selector):
    steps = pilot_steps()
    steps[1]["target"] = _target(selectors=[selector])
    mapped = _map(steps)
    click = _step_for(mapped, 2)

    assert click.action == "click"
    assert "role" not in click.element
    assert any(isinstance(v, str) and (selector in v or v in selector and len(v) > 3)
               for v in click.element.values())
    assert click.extra.get("strict") is True


# Interfaces: `map_version` never puts a role without an accessibleName into the
#             lookup cfg, so the strict lookup reaches the healed selector.
def test_a_role_without_an_accessible_name_is_left_out_of_the_lookup():
    steps = pilot_steps()
    steps[1]["target"] = _target(role="link", selectors=["#healed-link"])
    mapped = _map(steps)
    click = _step_for(mapped, 2)

    assert click.action == "click"
    assert "role" not in click.element
    assert has(click.element, "healed-link")


def test_a_button_role_and_name_maps_to_a_click_on_that_button():
    steps = pilot_steps()
    steps[2]["target"] = _target(role="button", name="Show author")
    mapped = _map(steps)
    click = _step_for(mapped, 3)

    assert click.action == "click"
    assert click.element.get("role") == "button"
    assert has(click.element, "Show author")


# Story: A text-entry step (target role `textbox` ...) healed to a role-less
#        element such as `{"placeholder": "Search"}` is proposed with the original
#        `role` (and no accessibleName) beside the new selector, so `map_version`
#        on the proposed steps maps it to a `fill` of the same value, not a
#        `click`, whose element cfg is the healed selector alone.
def test_a_textbox_role_beside_a_selector_still_maps_to_a_fill_on_the_selector_alone():
    from stepper.brightsky.targets import target_from_element

    steps = pilot_steps()
    original = steps[0]["target"]
    steps[0]["target"] = target_from_element({"placeholder": "Search"}, original)
    mapped = _map(steps)
    fill = _step_for(mapped, 1)

    assert fill.action == "fill"
    assert fill.input_value == "The Hobbit"
    assert "role" not in fill.element
    assert len(fill.element) == 1
    assert has(fill.element, "Search")


# Edge: A step with no target, a combobox/listbox/slider role, a textbox with no
#       quoted value, an unknown matchMode, or a navigate host other than the
#       workflow's `site` | the run fails with `step N: <reason>`
# Edge: A stored value that starts with `ENV:` / `${ENV:`, or any mapped text
#       containing `{{` | unmappable
def _no_target():
    steps = pilot_steps()
    del steps[1]["target"]
    return steps, 2


def _role(role):
    def make():
        steps = pilot_steps()
        steps[1]["target"] = _target(role=role, name="Sort by")
        return steps, 2
    make.__name__ = f"_{role}_role"
    return make


def _textbox_without_quoted_value():
    steps = pilot_steps()
    steps[0]["title"] = "Search for The Hobbit"
    steps[0]["explanation"] = "Type The Hobbit into the Search box and press Enter."
    return steps, 1


def _unknown_match_mode():
    steps = pilot_steps()
    steps[1]["matchMode"] = "glob"
    return steps, 2


def _navigate_to_another_host():
    steps = pilot_steps()
    steps[0]["expectedDomain"] = "attacker.example.com"
    return steps, 1


def _value(value):
    def make():
        steps = pilot_steps()
        steps[0]["title"] = f"Search for '{value}'"
        steps[0]["explanation"] = "Type it into the Search box and press Enter."
        return steps, 1
    make.__name__ = f"_value_{value[:6]}"
    return make


def _template_in_a_name():
    steps = pilot_steps()
    steps[2]["target"]["accessibleName"] = "{{author}}"
    return steps, 3


_UNMAPPABLE = [
    _no_target,
    _role("combobox"),
    _role("listbox"),
    _role("slider"),
    _textbox_without_quoted_value,
    _unknown_match_mode,
    _navigate_to_another_host,
    _value("ENV:BRIGHTSKY_BRIDGE_TOKEN"),
    _value("${ENV:BRIGHTSKY_BRIDGE_TOKEN}"),
    _value("{{query}}"),
    _template_in_a_name,
]


@pytest.mark.parametrize("make", _UNMAPPABLE, ids=lambda f: f.__name__.strip("_"))
def test_an_unmappable_step_raises_unmappable_step_with_its_number(make):
    from stepper.brightsky.mapping import UnmappableStep, map_version

    steps, number = make()

    with pytest.raises(UnmappableStep) as caught:
        map_version(workflow_detail(steps))

    assert getattr(caught.value, "step_number", None) == number
    assert getattr(caught.value, "reason", None) or str(caught.value)


# Interfaces: `mapping.url_matches(pathname, expected, mode) -> bool`: bright-sky's `matchUrl`.
# Edge: `matchMode: "regex"` that does not compile | it falls back to
#       `startsWith`, the same as BrightSky's `matchUrl`
@pytest.mark.parametrize("pathname,expected,mode,result", [
    ("/search", "/search", "startsWith", True),
    ("/search/inside", "/search", "startsWith", True),
    ("/books/search", "/search", "startsWith", False),
    ("/books/search", "/search", "includes", True),
    ("/books/find", "/search", "includes", False),
    ("/works/OL262758W", r"^/works/OL\d+W$", "regex", True),
    ("/works/abc", r"^/works/OL\d+W$", "regex", False),
    ("([abc", "([", "regex", True),
    ("/abc([", "([", "regex", False),
])
def test_url_matches_is_brightsky_match_url(pathname, expected, mode, result):
    from stepper.brightsky.mapping import url_matches

    assert url_matches(pathname, expected, mode) is result


# Interfaces: `targets.target_from_element(element, original=None) -> dict | None`:
#             a stepper element cfg as a BrightSky `PlanStepTarget`, or None
#             when the store cannot express it.
def _valid_plan_step_target(target):
    assert isinstance(target, dict)
    assert isinstance(target["selectors"], list) and len(target["selectors"]) <= 5
    assert all(isinstance(s, str) for s in target["selectors"])
    assert 0 <= target["score"] <= 1
    assert target["grounding"] in ("current_page", "future_page", "break_point")
    named = bool(str(target.get("role", "")).strip()) and bool(target.get("accessibleName"))
    assert named or target["selectors"], "a target needs role+name or a selector"


def test_a_css_element_becomes_a_selector_target():
    from stepper.brightsky.targets import target_from_element

    target = target_from_element({"css": "#healed-link"})

    _valid_plan_step_target(target)
    assert "#healed-link" in target["selectors"]


def test_an_xpath_element_becomes_a_selector_target():
    from stepper.brightsky.targets import target_from_element

    target = target_from_element({"xpath": "//a[@data-test='title']"})

    _valid_plan_step_target(target)
    assert any("//a[@data-test='title']" in s for s in target["selectors"])


def test_an_id_element_becomes_a_selector_target():
    from stepper.brightsky.targets import target_from_element

    target = target_from_element({"id": "searchbox"})

    _valid_plan_step_target(target)
    assert any("searchbox" in s for s in target["selectors"])


def test_a_role_and_name_element_becomes_a_role_and_accessible_name_target():
    from stepper.brightsky.targets import target_from_element

    target = target_from_element({"role": "link", "name": "The Hobbit"})

    _valid_plan_step_target(target)
    assert target["role"] == "link"
    assert target["accessibleName"] == "The Hobbit"


# Edge: A heal whose new element has no role+name, no css, no xpath and no id
#       (only text) | the run is reported failed; nothing is proposed
def test_a_text_only_element_cannot_be_expressed():
    from stepper.brightsky.targets import target_from_element

    assert target_from_element({"text": "The Hobbit"}) is None


# Interfaces: When `element` has no role+name, only the original target's `role`
#             is kept beside the healed selectors ... The old accessibleName is dropped.
def test_a_role_less_heal_keeps_only_the_original_role():
    from stepper.brightsky.targets import target_from_element

    original = pilot_steps()[0]["target"]
    target = target_from_element({"placeholder": "Search"}, original)

    _valid_plan_step_target(target)
    assert target["role"] == "textbox"
    assert not target.get("accessibleName")
    assert target["selectors"] and any("Search" in s for s in target["selectors"])
