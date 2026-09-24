"""
phpTravels' one workflow had never run. Running it found two defects.

The site shipped four actions and `hotel_booking.json`, and nothing had ever
executed them: this environment's egress policy denies phptravels.com and there
was no CI step for the site. `validate` said the wiring was sound, which is all
it can say. Against local fixtures (stepper/sites/phptravels/fixtures/):

  1. HotelDetailPage's constructor omitted `behaviour`, alone of the site's
     four POMs. _build_pom passes it as a keyword to every POM, so
     pt_book_hotel died on

         TypeError: __init__() got an unexpected keyword argument 'behaviour'

     which the glue's `except Exception` reported as an ordinary failed step.
     The last step of the site's only workflow had never once run. That rule
     now lives in test_pom_behaviour_optional.py, repo-wide — it found the
     same omission in saucedemo's ProductPage.

  2. The typeahead suggestion was a Locator going through _interact, and that
     cannot work. A typeahead exists to offer several matches; the cascade
     resolves exactly one element and treats 2+ as ambiguity. Typing "Dubai"
     produced two suggestions, the deterministic phase fell through, the
     semantic phase could not match the description "first autocomplete
     suggestion" against the text "Dubai"/"Dubai Marina", and the step failed.
     It would only ever have worked when a query happened to match exactly one.

The second is the interesting one: it is not a typo, it is a category error —
a collection addressed as if it were an element. pom-layer.md has the rule;
this file pins it for the one place that got it wrong.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from stepper.engine.interfaces import ExecutionContext, StepConfig


# ── Rule 1: the typeahead is a collection ─────────────────────────────────────

def test_the_suggestion_selector_is_not_a_locator():
    """
    A regression pin on a type. As a Locator it goes through _interact and the
    cascade; as a plain string it goes through query_selector_all and an index,
    which is what "first suggestion" actually means.
    """
    from poms.shared.locator import Locator
    from poms.phpTravels.pages.home_page import HomePage

    item = HomePage.Locators.SUGGESTION_ITEM

    assert not isinstance(item, Locator), (
        "SUGGESTION_ITEM must be a plain CSS string. A typeahead offers several "
        "matches by design, and the resolver cascade refuses 2+ as ambiguous — "
        "so routing it through _interact fails on every query but a unique one."
    )
    assert isinstance(item, str)


def _home_page(suggestions: int):
    from poms.phpTravels.pages.home_page import HomePage

    clicked = []
    elements = []
    for i in range(suggestions):
        el = MagicMock()

        async def _click(_i=i):
            clicked.append(_i)

        el.click = _click
        elements.append(el)

    driver = MagicMock()

    async def _all(selector):
        return elements

    driver.query_selector_all = _all
    return HomePage(driver, "https://example.test", page=MagicMock(),
                    resolver=None, behaviour=None), clicked


def test_the_first_suggestion_is_taken_when_several_are_offered():
    """The case that broke it: more than one match is normal, not an error."""
    home, clicked = _home_page(suggestions=3)

    assert asyncio.run(home.select_first_hotel_suggestion()) is True
    assert clicked == [0], "it must click the first, not fail on the ambiguity"


def test_an_empty_suggestion_menu_reports_false():
    home, clicked = _home_page(suggestions=0)

    assert asyncio.run(home.select_first_hotel_suggestion()) is False
    assert clicked == []


# ── Rule 2: a missed interaction fails the step ───────────────────────────────

def _actions():
    from stepper.sites.phptravels.pages.hotel_detail_action import PTHotelDetailPage
    from stepper.sites.phptravels.pages.hotel_search_action import PTHotelSearchPage
    from stepper.sites.phptravels.pages.login_action import PTLoginPage

    return [
        (PTLoginPage.PTLoginAction(),
         {"email": "e@example.test", "password": "p"}),
        (PTHotelSearchPage.PTSearchHotelsAction(),
         {"destination": "Dubai", "checkin": "01-01-2027", "checkout": "02-01-2027"}),
        (PTHotelDetailPage.PTBookHotelAction(),
         {"checkin": "01-01-2027", "checkout": "02-01-2027"}),
    ]


@pytest.fixture
def every_lookup_misses(monkeypatch):
    """Nothing on the page resolves — _interact answers False, as it does."""
    from poms.shared.base_page import BasePage

    async def _false(self, locator, action, **kwargs):
        return False

    async def _noop(self, *a, **k):
        return None

    monkeypatch.setattr(BasePage, "_interact", _false)
    monkeypatch.setattr(BasePage, "open", _noop, raising=False)


def _empty_driver() -> MagicMock:
    async def _none(*a, **k):
        return None

    async def _empty(*a, **k):
        return []

    async def _zero(*a, **k):
        return 0

    driver = MagicMock()
    driver.query_selector = _none
    driver.query_selector_all = _empty
    driver.wait_for_selector = _none
    driver.wait_for_load_state = _none
    driver.goto = _none
    driver.locator_count = _zero
    return driver


@pytest.mark.parametrize("action, extra", _actions(),
                         ids=[a.action_name for a, _ in _actions()])
def test_a_missed_interaction_fails_the_step(action, extra, every_lookup_misses):
    page = MagicMock()
    page.url = "http://127.0.0.1/wherever"
    action._driver = lambda _page: _empty_driver()

    step = StepConfig(action=action.action_name, description="probe", extra=extra)
    result = asyncio.run(action.execute(page, step, MagicMock(),
                                        ExecutionContext(), None))

    assert result.status == "failed", (
        f"{action.action_name} reported {result.status!r} with nothing on the page"
    )
    assert action.action_name in (result.error or "")
