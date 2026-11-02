"""
stepper.brightsky.targets: a healed stepper element cfg as a BrightSky target.

target_from_element is pure. Its output must pass bright-sky's
readPlanStepTarget, and a proposed step built from it must map back through
map_version to the same action: a healed text-entry step stays a `fill`, and
the stale accessibleName never reaches the strict lookup.
"""
from __future__ import annotations

import copy

import pytest

from stepper.brightsky.mapping import MappedWorkflow, map_version
from stepper.brightsky.models import WorkflowDetail
from stepper.brightsky.targets import target_from_element

SITE = "openlibrary.org"

#: A pilot-like step 1, as in bright-sky's
#: backend/src/workflow-store/pilot-workflows.ts (openlibrary-find-author).
STEP_1: dict = {
    "title": "Search for 'The Hobbit'",
    "explanation": "On the Open Library home page, type 'The Hobbit' into the Search box and press Enter.",
    "expectedDomain": "openlibrary.org",
    "expectedUrl": "/",
    "target": {"role": "textbox", "accessibleName": "Search", "selectors": [],
               "score": 0.8, "grounding": "current_page"},
    "expectedOutcome": {"kind": "url_change", "urlContains": "/search"},
}

GROUNDINGS = ("current_page", "future_page", "break_point")


def _valid_plan_step_target(target: dict) -> None:
    """A copy of readPlanStepTarget's rules (bright-sky, step-target.ts)."""
    assert isinstance(target, dict)
    selectors = target["selectors"]
    assert isinstance(selectors, list) and len(selectors) <= 5
    for s in selectors:
        assert isinstance(s, str) and s.strip() and len(s) <= 1024
    score = target["score"]
    assert isinstance(score, (int, float)) and not isinstance(score, bool)
    assert 0 <= score <= 1
    assert target["grounding"] == "current_page"
    assert target["grounding"] in GROUNDINGS
    role = target.get("role")
    name = target.get("accessibleName")
    assert role is None or (isinstance(role, str) and len(role) <= 64)
    assert name is None or (isinstance(name, str) and len(name) <= 512)
    named = bool(role and role.strip()) and bool(name and name.strip())
    assert named or selectors, "a target needs role+name or a selector"


def _detail_json(steps: list[dict]) -> dict:
    return {
        "slug": "openlibrary-find-author",
        "site": SITE,
        "currentVersion": {"version": 2},
        "currentSteps": steps,
        "versions": [{"version": 1, "note": None}, {"version": 2, "note": None}],
    }


def _healed(healed: dict) -> MappedWorkflow:
    """Step 1 with its target replaced by the healed one, read and mapped again."""
    step = copy.deepcopy(STEP_1)
    step["target"] = target_from_element(healed, original=step["target"])
    assert step["target"] is not None
    _valid_plan_step_target(step["target"])
    return map_version(WorkflowDetail.from_json(_detail_json([step])))


def _step_1(mapped: MappedWorkflow):
    found = [s for s in mapped.steps
             if s.action != "navigate" and mapped.step_numbers[s.description] == 1]
    assert len(found) == 1
    return found[0]


# ── each element kind ────────────────────────────────────────────────────────

@pytest.mark.parametrize("element, expected", [
    ({"role": "link", "name": "The Hobbit"},
     {"role": "link", "accessibleName": "The Hobbit", "selectors": []}),
    ({"css": "a.result-title"}, {"selectors": ["a.result-title"]}),
    ({"xpath": "//a[@data-test='title']"}, {"selectors": ["//a[@data-test='title']"]}),
    ({"id": "searchbox"}, {"selectors": ["#searchbox"]}),
    ({"placeholder": "Search"}, {"selectors": ['[placeholder="Search"]']}),
    ({"placeholder": 'Say "hi"'}, {"selectors": ['[placeholder="Say \\"hi\\""]']}),
    ({"placeholder": "a\\b"}, {"selectors": ['[placeholder="a\\\\b"]']}),
    ({"role": "button", "name": "Go", "css": "button.go"},
     {"role": "button", "accessibleName": "Go", "selectors": ["button.go"]}),
], ids=["role+name", "css", "xpath", "id", "placeholder", "placeholder-quote",
        "placeholder-backslash", "role+name+css"])
def test_each_element_kind_becomes_a_target(element, expected):
    target = target_from_element(element)

    _valid_plan_step_target(target)
    assert target == {**expected, "score": 0.8, "grounding": "current_page"}


def test_a_quoted_placeholder_stays_one_css_attribute_selector():
    target = target_from_element({"placeholder": 'Say "hi"'})

    assert target["selectors"] == [r'[placeholder="Say \"hi\""]']


def test_several_selector_keys_are_all_kept():
    target = target_from_element({"placeholder": "Search", "id": "q",
                                  "css": "input.q", "xpath": "//input"})

    _valid_plan_step_target(target)
    assert set(target["selectors"]) == {'[placeholder="Search"]', "#q", "input.q", "//input"}


# ── what the store cannot express ────────────────────────────────────────────

@pytest.mark.parametrize("element", [
    {"text": "x"},
    {"label": "x"},
    {},
    {"role": "link", "name": "  "},
    {"role": "link"},
    {"name": "x"},
    None,
    "#css",
    ["css"],
    42,
], ids=["text", "label", "empty", "blank-name", "role-only", "name-only", "None",
        "str", "list", "int"])
def test_an_element_the_store_cannot_express_is_none(element):
    assert target_from_element(element) is None


def test_a_text_only_element_is_none_even_with_an_original_role():
    assert target_from_element({"text": "x"}, original=STEP_1["target"]) is None


def test_a_2000_character_css_is_dropped():
    long_css = "a" * 2000

    assert target_from_element({"css": long_css}) is None
    target = target_from_element({"css": long_css, "id": "q"})
    _valid_plan_step_target(target)
    assert target["selectors"] == ["#q"]


@pytest.mark.parametrize("element", [
    {"css": 5},
    {"css": "   "},
    {"xpath": ["//a"]},
    {"id": ""},
    {"placeholder": None},
    {"role": 1, "name": "Go"},
    {"role": "link", "name": {"x": 1}},
], ids=["css-int", "css-blank", "xpath-list", "id-empty", "placeholder-None",
        "role-int", "name-dict"])
def test_values_that_are_not_non_blank_strings_are_ignored(element):
    assert target_from_element(element) is None


# ── the original target ──────────────────────────────────────────────────────

def test_a_role_less_heal_keeps_only_the_original_role():
    original = {"role": "textbox", "accessibleName": "Search",
                "selectors": ["input.stale"], "score": 0.9, "grounding": "current_page"}

    target = target_from_element({"placeholder": "Search"}, original)

    _valid_plan_step_target(target)
    assert target == {"role": "textbox", "selectors": ['[placeholder="Search"]'],
                      "score": 0.8, "grounding": "current_page"}


def test_an_element_role_and_name_win_over_the_original_role():
    target = target_from_element({"role": "searchbox", "name": "Find"}, STEP_1["target"])

    _valid_plan_step_target(target)
    assert target["role"] == "searchbox"
    assert target["accessibleName"] == "Find"


@pytest.mark.parametrize("original", [
    None, "textbox", {"role": "  ", "accessibleName": "Search"}, {"role": 3},
    {"accessibleName": "Search"},
], ids=["None", "not-a-dict", "blank-role", "int-role", "no-role"])
def test_an_unusable_original_adds_no_role(original):
    target = target_from_element({"css": "input.q"}, original)

    _valid_plan_step_target(target)
    assert "role" not in target
    assert "accessibleName" not in target
    assert target["selectors"] == ["input.q"]


def test_the_original_is_not_changed():
    original = copy.deepcopy(STEP_1["target"])

    target_from_element({"placeholder": "Search"}, original)

    assert original == STEP_1["target"]


# ── the round trip through map_version ───────────────────────────────────────

@pytest.mark.parametrize("healed, cfg_key, cfg_value", [
    ({"placeholder": "Search"}, "css", '[placeholder="Search"]'),
    ({"css": "input.search-bar"}, "css", "input.search-bar"),
    ({"id": "searchbox"}, "id", "searchbox"),
], ids=["placeholder", "css", "id"])
def test_a_role_less_heal_of_step_1_still_maps_to_a_fill(healed, cfg_key, cfg_value):
    fill = _step_1(_healed(healed))

    assert fill.action == "fill"
    assert fill.input_value == "The Hobbit"
    assert fill.extra["press_enter"] is True
    assert fill.element == {cfg_key: cfg_value}
    assert "name" not in fill.element
    assert "role" not in fill.element
    # The stale accessibleName `Search` is nowhere in the cfg as a value of its own.
    assert "Search" not in fill.element.values()
    assert "text" not in fill.element


def test_a_role_and_name_heal_of_step_1_keeps_the_new_role_and_name():
    fill = _step_1(_healed({"role": "searchbox", "name": "Find"}))

    assert fill.action == "fill"
    assert fill.input_value == "The Hobbit"
    assert fill.extra["press_enter"] is True
    assert fill.element == {"role": "searchbox", "name": "Find"}
    assert "Search" not in fill.element.values()


def test_without_the_original_a_role_less_heal_would_become_a_click():
    """Why `original` exists: the healed selector alone does not say `fill`."""
    step = copy.deepcopy(STEP_1)
    step["target"] = target_from_element({"placeholder": "Search"})

    mapped = map_version(WorkflowDetail.from_json(_detail_json([step])))

    assert _step_1(mapped).action == "click"
