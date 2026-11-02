"""
stepper.brightsky.mapping: BrightSky steps as strict stepper steps.

map_version is pure and owns two gates: the host guard (a stored workflow
cannot steer the headless browser off its own site) and `extra.strict: true`
on every acting step (a wrong element is never clicked and reported passed).
It also keeps stored text away from the engine's `{{…}}` and `ENV:` lookups.
url_matches is bright-sky's matchUrl.
"""
from __future__ import annotations

import copy

import pytest

from stepper.brightsky.mapping import (
    MappedWorkflow,
    StepExpectation,
    UnmappableStep,
    map_version,
    url_matches,
)
from stepper.brightsky.models import WorkflowDetail

SITE = "openlibrary.org"

#: The pilot's steps, copied from bright-sky's
#: backend/src/workflow-store/pilot-workflows.ts (openlibrary-find-author).
PILOT_STEPS: list[dict] = [
    {
        "title": "Search for 'The Hobbit'",
        "explanation": "On the Open Library home page, type 'The Hobbit' into the Search box and press Enter. A list of matching books will appear.",
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/",
        "target": {"role": "textbox", "accessibleName": "Search", "selectors": [],
                   "score": 0.8, "grounding": "current_page"},
        "expectedOutcome": {"kind": "url_change", "urlContains": "/search"},
    },
    {
        "title": "Open the book page",
        "explanation": "In the search results, click the title 'The Hobbit'. This opens the book's page with its description and editions.",
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/search",
        "target": {"role": "link", "accessibleName": "The Hobbit", "selectors": [],
                   "score": 0.8, "grounding": "current_page"},
        "expectedOutcome": {"kind": "url_change", "urlContains": "/works/"},
    },
    {
        "title": "Open the author page",
        "explanation": "On the book page, click the author's name, 'J.R.R. Tolkien'. This opens the author's page with their biography and other books.",
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/works/",
        "target": {"role": "link", "accessibleName": "J.R.R. Tolkien", "selectors": [],
                   "score": 0.8, "grounding": "current_page"},
        "expectedOutcome": {"kind": "url_change", "urlContains": "/authors/"},
    },
]


def _steps() -> list[dict]:
    return copy.deepcopy(PILOT_STEPS)


def _detail(steps: list[dict] | None = None, site: str = SITE) -> WorkflowDetail:
    return WorkflowDetail(slug="openlibrary-find-author", site=site, current_version=1,
                          steps=_steps() if steps is None else steps,
                          versions=[(1, None)])


def _target(role: str | None = None, name: str | None = None,
            selectors: list | None = None) -> dict:
    target: dict = {"selectors": selectors or [], "score": 0.8,
                    "grounding": "current_page"}
    if role is not None:
        target["role"] = role
    if name is not None:
        target["accessibleName"] = name
    return target


def _acting(mapped: MappedWorkflow, number: int):
    found = [s for s in mapped.steps
             if s.action != "navigate" and mapped.step_numbers[s.description] == number]
    assert len(found) == 1
    return found[0]


def _unmappable(steps: list[dict], site: str = SITE) -> UnmappableStep:
    with pytest.raises(UnmappableStep) as caught:
        map_version(_detail(steps, site))
    return caught.value


# ── the pilot ────────────────────────────────────────────────────────────────

def test_the_pilot_maps_to_navigate_fill_click_click():
    mapped = map_version(_detail())

    assert [s.action for s in mapped.steps] == ["navigate", "fill", "click", "click"]
    navigate, fill, hobbit, tolkien = mapped.steps
    assert navigate.url == "https://openlibrary.org/"
    assert navigate.description == "Step 1: open https://openlibrary.org/"
    assert mapped.step_numbers[navigate.description] == 1
    assert navigate.description not in mapped.expectations

    assert fill.input_value == "The Hobbit"
    assert fill.element == {"role": "textbox", "name": "Search"}
    assert fill.extra["press_enter"] is True
    assert fill.heal_assert == {"url_contains": "/search"}
    assert hobbit.element == {"role": "link", "name": "The Hobbit"}
    assert tolkien.element == {"role": "link", "name": "J.R.R. Tolkien"}
    assert "press_enter" not in hobbit.extra

    for step in (fill, hobbit, tolkien):
        assert step.extra["strict"] is True
    assert [mapped.step_numbers[s.description] for s in (fill, hobbit, tolkien)] == [1, 2, 3]
    assert fill.description == "Step 1: Search for 'The Hobbit'"
    assert tolkien.description == "Step 3: Open the author page"


def test_the_pilot_expectations():
    mapped = map_version(_detail())
    first, second, third = (mapped.expectations[s.description] for s in mapped.steps[1:])

    assert first == StepExpectation(start_url=None, match_mode=None,
                                    outcome_kind="url_change", outcome_element=None,
                                    url_contains="/search")
    assert second.start_url == "/search" and second.match_mode is None
    assert second.url_contains == "/works/"
    assert third.start_url == "/works/"
    assert third.outcome_kind == "url_change"


def test_descriptions_are_unique_even_for_equal_titles():
    steps = _steps()
    steps[2]["title"] = steps[1]["title"]
    mapped = map_version(_detail(steps))

    descriptions = [s.description for s in mapped.steps]
    assert len(set(descriptions)) == len(descriptions)


# ── target kinds ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target,element", [
    (_target("button", "Show author"), {"role": "button", "name": "Show author"}),
    (_target(name="The Hobbit"), {"text": "The Hobbit"}),
    (_target(selectors=[".searchResultItem a.results"]), {"css": ".searchResultItem a.results"}),
    (_target(selectors=["//a[@data-test='book-title']"]), {"xpath": "//a[@data-test='book-title']"}),
    (_target(selectors=["(//a)[1]"]), {"xpath": "(//a)[1]"}),
    (_target(selectors=["#search-results-first"]), {"id": "search-results-first"}),
    (_target(selectors=["#a b"]), {"css": "#a b"}),
    (_target("link", "The Hobbit", ["a.title", "#other"]),
     {"role": "link", "name": "The Hobbit", "css": "a.title"}),
    (_target("link", selectors=["#healed-link"]), {"id": "healed-link"}),
    (_target("link", "   ", ["a.x"]), {"css": "a.x"}),
], ids=["role+name", "text-only", "css", "xpath", "xpath-paren", "id", "css-hash",
        "role+name+selector", "role-without-name", "blank-name"])
def test_target_kinds(target, element):
    steps = _steps()
    steps[1]["target"] = target
    click = _acting(map_version(_detail(steps)), 2)

    assert click.action == "click"
    assert click.element == element
    assert click.extra["strict"] is True


def test_a_textbox_without_a_name_fills_through_its_selector_alone():
    steps = _steps()
    steps[0]["target"] = _target("textbox", selectors=['[placeholder="Search"]'])
    fill = _acting(map_version(_detail(steps)), 1)

    assert fill.action == "fill"
    assert fill.element == {"css": '[placeholder="Search"]'}
    assert "role" not in fill.element
    assert fill.input_value == "The Hobbit"
    assert fill.extra == {"strict": True, "press_enter": True}


@pytest.mark.parametrize("role", ["searchbox", "spinbutton", "TextBox"])
def test_other_text_entry_roles_fill(role):
    steps = _steps()
    steps[0]["target"] = _target(role, "Search")
    assert _acting(map_version(_detail(steps)), 1).action == "fill"


def test_a_value_set_outcome_fills_without_enter():
    steps = _steps()
    steps[1]["title"] = 'Type "Tolkien" in the author field'
    steps[1]["target"] = _target(selectors=["#author"])
    steps[1]["expectedOutcome"] = {"kind": "value_set",
                                   "target": _target(selectors=["#author"])}
    mapped = map_version(_detail(steps))
    fill = _acting(mapped, 2)

    assert fill.action == "fill"
    assert fill.input_value == "Tolkien"
    assert fill.extra == {"strict": True}
    assert fill.heal_assert is None
    expectation = mapped.expectations[fill.description]
    assert expectation.outcome_kind == "value_set"
    assert expectation.outcome_element == {"id": "author"}


def test_the_value_comes_from_the_explanation_when_the_title_has_none():
    steps = _steps()
    steps[0]["title"] = "Search for a book"
    fill = _acting(map_version(_detail(steps)), 1)
    assert fill.input_value == "The Hobbit"


def test_an_apostrophe_is_not_a_quote():
    steps = _steps()
    steps[0]["title"] = "Search the library's catalogue"
    steps[0]["explanation"] = "Type 'Dune' into the author's search box."
    fill = _acting(map_version(_detail(steps)), 1)
    assert fill.input_value == "Dune"


@pytest.mark.parametrize("kind", ["element_gone", "element_appears"])
def test_element_outcomes_record_the_outcome_element(kind):
    steps = _steps()
    steps[1]["expectedOutcome"] = {"kind": kind, "target": _target("dialog", "Results")}
    mapped = map_version(_detail(steps))
    click = _acting(mapped, 2)

    expectation = mapped.expectations[click.description]
    assert expectation.outcome_kind == kind
    assert expectation.outcome_element == {"role": "dialog", "name": "Results"}
    assert expectation.url_contains is None
    assert click.heal_assert is None


def test_a_url_change_without_url_contains_has_no_heal_assert():
    steps = _steps()
    steps[1]["expectedOutcome"] = {"kind": "url_change"}
    mapped = map_version(_detail(steps))
    click = _acting(mapped, 2)
    assert click.heal_assert is None
    assert mapped.expectations[click.description].outcome_kind == "url_change"


def test_no_outcome_records_no_outcome():
    steps = _steps()
    del steps[1]["expectedOutcome"]
    mapped = map_version(_detail(steps))
    expectation = mapped.expectations[_acting(mapped, 2).description]
    assert expectation.outcome_kind is None
    assert expectation.start_url == "/search"


# ── navigate host and path ───────────────────────────────────────────────────

def test_the_navigate_host_falls_back_to_the_site_and_the_path_to_slash():
    steps = _steps()
    del steps[0]["expectedDomain"]
    steps[0]["expectedUrl"] = "/search"
    steps[0]["matchMode"] = "includes"
    assert map_version(_detail(steps)).steps[0].url == "https://openlibrary.org/"


@pytest.mark.parametrize("mode", [None, "startsWith"])
def test_the_navigate_path_is_the_expected_url(mode):
    steps = _steps()
    steps[0]["expectedUrl"] = "/books/new"
    if mode:
        steps[0]["matchMode"] = mode
    assert map_version(_detail(steps)).steps[0].url == "https://openlibrary.org/books/new"


@pytest.mark.parametrize("url", ["search", "https://evil.com/", ""])
def test_a_navigate_path_not_starting_with_slash_is_slash(url):
    steps = _steps()
    steps[0]["expectedUrl"] = url
    assert map_version(_detail(steps)).steps[0].url == "https://openlibrary.org/"


@pytest.mark.parametrize("host", ["www.openlibrary.org", "OpenLibrary.ORG"])
def test_a_subdomain_or_other_case_of_the_site_is_allowed(host):
    steps = _steps()
    steps[0]["expectedDomain"] = host
    assert map_version(_detail(steps)).steps[0].url == f"https://{host.lower()}/"


@pytest.mark.parametrize("host", [
    "evil.com",
    "openlibrary.org.evil.com",
    "user@openlibrary.org",
    "openlibrary.org:8080",
    "127.0.0.1",
    "openlibrary.org/..",
    "evilopenlibrary.org",
    "evil.com\\openlibrary.org",
    "evil.com openlibrary.org",
    "evil.com#.openlibrary.org",
    "evil.com?.openlibrary.org",
    ".openlibrary.org",
    "",
])
def test_the_host_guard_refuses_a_navigate_host_off_the_site(host):
    steps = _steps()
    steps[0]["expectedDomain"] = host
    error = _unmappable(steps)

    assert error.step_number == 1
    assert "is not the workflow's site openlibrary.org" in error.reason
    assert error.reason.startswith("navigate host ")


@pytest.mark.parametrize("site", ["127.0.0.1", "10.0.0.5", "[::1]", "::1", "2130706433",
                                  "0x7f000001", "evil.com/x", "user@evil.com", "com"])
def test_the_host_guard_refuses_a_site_that_is_not_a_host_name(site):
    steps = _steps()
    for step in steps:
        step["expectedDomain"] = site
    error = _unmappable(steps, site=site)
    assert error.step_number == 1


def test_a_hostile_host_is_not_echoed_raw():
    steps = _steps()
    steps[0]["expectedDomain"] = "evil.com\x1b[2J\n"
    error = _unmappable(steps)
    assert "\x1b" not in error.reason and "\n" not in error.reason


@pytest.mark.parametrize("host", ["evil.com", "openlibrary.org.evil.com", "a@openlibrary.org"])
def test_a_later_steps_expected_domain_passes_the_same_check(host):
    steps = _steps()
    steps[2]["expectedDomain"] = host
    error = _unmappable(steps)
    assert error.step_number == 3
    assert "is not the workflow's site openlibrary.org" in error.reason


# ── unmappable steps ─────────────────────────────────────────────────────────

def _no_target(steps):
    del steps[1]["target"]
    return 2, "step has no target"


def _empty_target(steps):
    steps[1]["target"] = _target(selectors=["   "])
    return 2, "step has no target"


def _role_only_target(steps):
    steps[1]["target"] = _target("link")
    return 2, "step has no target"


def _unsupported(role):
    def make(steps):
        steps[1]["target"] = _target(role, "Sort by")
        return 2, f"role {role} is not supported yet"
    make.__name__ = role
    return make


def _no_value(steps):
    steps[0]["title"] = "Search for The Hobbit"
    steps[0]["explanation"] = "Type The Hobbit into the Search box and press Enter."
    return 1, "no value to type: quote it in the title"


def _unknown_match_mode(steps):
    steps[1]["matchMode"] = "glob"
    return 2, "matchMode"


def _unknown_match_mode_first(steps):
    steps[0]["matchMode"] = "glob"
    return 1, "matchMode"


def _unknown_outcome(steps):
    steps[2]["expectedOutcome"] = {"kind": "teleport"}
    return 3, "outcome"


def _outcome_without_target(steps):
    steps[2]["expectedOutcome"] = {"kind": "element_gone"}
    return 3, "outcome"


def _value(value):
    def make(steps):
        steps[0]["title"] = f"Search for '{value}'"
        return 1, ("value names an environment variable" if "ENV:" in value
                   else "contains a {{…}} template reference")
    make.__name__ = value
    return make


def _template_in(where):
    def make(steps):
        if where == "title":
            steps[1]["title"] = "Open {{book}}"
        elif where == "name":
            steps[1]["target"]["accessibleName"] = "{{author}}"
        elif where == "selector":
            steps[1]["target"] = _target(selectors=["a[title='{{x}}']"])
        elif where == "url":
            steps[0]["expectedUrl"] = "/{{path}}"
            return 1, "contains a {{…}} template reference"
        elif where == "url_contains":
            steps[1]["expectedOutcome"] = {"kind": "url_change", "urlContains": "{{x}}"}
        elif where == "outcome_target":
            steps[1]["expectedOutcome"] = {"kind": "element_appears",
                                           "target": _target(name="{{x}}")}
        return 2, "contains a {{…}} template reference"
    make.__name__ = f"template_in_{where}"
    return make


@pytest.mark.parametrize("make", [
    _no_target, _empty_target, _role_only_target,
    _unsupported("combobox"), _unsupported("listbox"), _unsupported("slider"),
    _no_value, _unknown_match_mode, _unknown_match_mode_first,
    _unknown_outcome, _outcome_without_target,
    _value("ENV:BRIGHTSKY_BRIDGE_TOKEN"), _value("${ENV:BRIGHTSKY_BRIDGE_TOKEN}"),
    _value(" ENV:HOME"), _value("{{token}}"),
    _template_in("title"), _template_in("name"), _template_in("selector"),
    _template_in("url"), _template_in("url_contains"), _template_in("outcome_target"),
], ids=lambda f: f.__name__.strip("_"))
def test_unmappable_steps_name_their_number_and_reason(make):
    steps = _steps()
    number, reason = make(steps)
    error = _unmappable(steps)

    assert error.step_number == number
    assert reason in error.reason
    assert str(error) == f"step {number}: {error.reason}"


def test_the_env_value_is_refused_before_anything_is_returned():
    steps = _steps()
    steps[0]["title"] = "Search for 'ENV:BRIGHTSKY_BRIDGE_TOKEN'"
    error = _unmappable(steps)
    assert error.step_number == 1
    assert error.reason == "value names an environment variable"


def test_a_template_in_the_title_is_refused():
    steps = _steps()
    steps[0]["title"] = "Search for '{{token}}'"
    error = _unmappable(steps)
    assert error.step_number == 1
    assert error.reason == "contains a {{…}} template reference"


@pytest.mark.parametrize("field,value", [
    ("target", "link"), ("expectedOutcome", "url_change"), ("expectedDomain", 5),
    ("expectedUrl", ["/"]), ("matchMode", 1), ("matchMode", []), ("matchMode", {}),
    ("expectedOutcome", {"kind": []}), ("expectedOutcome", {"kind": {}}),
    ("explanation", 3),
])
def test_wrong_types_are_unmappable(field, value):
    steps = _steps()
    steps[1][field] = value
    assert _unmappable(steps).step_number == 2


@pytest.mark.parametrize("field,value", [
    ("matchMode", []), ("matchMode", {}),
    ("expectedOutcome", {"kind": []}), ("expectedOutcome", {"kind": {}}),
])
def test_unhashable_mode_or_kind_on_step_1_is_unmappable(field, value):
    steps = _steps()
    steps[0][field] = value
    assert _unmappable(steps).step_number == 1


def test_wrong_target_field_types_are_unmappable():
    steps = _steps()
    steps[1]["target"] = {"role": 3, "accessibleName": "x", "selectors": []}
    assert _unmappable(steps).step_number == 2
    steps[1]["target"] = {"selectors": "a.x"}
    assert _unmappable(steps).step_number == 2
    steps[1]["target"] = {"selectors": [5]}
    assert _unmappable(steps).step_number == 2


# ── url_matches (bright-sky's matchUrl) ──────────────────────────────────────

@pytest.mark.parametrize("pathname,expected,mode,result", [
    ("/search", "/search", "startsWith", True),
    ("/search/inside", "/search", "startsWith", True),
    ("/books/search", "/search", "startsWith", False),
    ("/books/search", "/search", None, False),
    ("/search", "/search", None, True),
    ("/books/search", "/search", "includes", True),
    ("/books/find", "/search", "includes", False),
    ("/works/OL262758W", r"^/works/OL\d+W$", "regex", True),
    ("/works/abc", r"^/works/OL\d+W$", "regex", False),
    ("/a/works/OL1W", r"works/OL\d+W", "regex", True),
    ("([abc", "([", "regex", True),
    ("/abc([", "([", "regex", False),
])
def test_url_matches_is_brightsky_match_url(pathname, expected, mode, result):
    assert url_matches(pathname, expected, mode) is result
