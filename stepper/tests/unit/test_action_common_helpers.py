"""
actions/_common.py — the helpers shared across the action modules.

Small functions, but `_resolve_input_value` and `_checked_input_value` are how
credentials reach a form. A workflow says `"input_value": "ENV:SD_PASSWORD"` and
these decide what actually gets typed.

The failure that matters is the quiet one: an env var that is not set resolving
to "" and being filled into a password field. The form then submits with a blank
password, the site rejects it, and the run reports a login failure — pointing at
the site, the selector, or the credentials themselves, never at the missing
variable. `_checked_input_value` exists to turn that into a named error, and
that is what most of this file is about.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions._common import (
    _checked_input_value,
    _fetch_attr,
    _resolve_input_value,
    _wait_for,
)
from stepper.engine.interfaces import StepConfig


# ── Resolving a value ─────────────────────────────────────────────────────────

def test_a_plain_value_is_returned_unchanged():
    assert _resolve_input_value("Dune") == ("Dune", False)


@pytest.mark.parametrize("spelling", ["ENV:SD_PASSWORD", "${ENV:SD_PASSWORD}"])
def test_both_env_spellings_resolve(spelling, monkeypatch):
    monkeypatch.setenv("SD_PASSWORD", "secret_sauce")

    assert _resolve_input_value(spelling) == ("secret_sauce", True)


@pytest.mark.parametrize("spelling", ["ENV:NOT_SET", "${ENV:NOT_SET}"])
def test_an_unset_variable_resolves_to_empty_but_is_flagged(spelling, monkeypatch):
    """
    The flag is the whole point. "" on its own is indistinguishable from a
    deliberately empty value; the second element of the tuple is what lets the
    caller tell them apart.
    """
    monkeypatch.delenv("NOT_SET", raising=False)

    assert _resolve_input_value(spelling) == ("", True)


def test_a_value_that_merely_mentions_env_is_not_a_reference():
    """Only a prefix counts — a search term should not be resolved."""
    assert _resolve_input_value("search for ENV:PATH") == ("search for ENV:PATH", False)


def test_a_non_string_passes_straight_through():
    """extra values are an open bag; an int must not hit .startswith()."""
    assert _resolve_input_value(42) == (42, False)      # type: ignore[arg-type]
    assert _resolve_input_value(None) == (None, False)  # type: ignore[arg-type]


def test_an_empty_string_is_not_an_env_reference():
    assert _resolve_input_value("") == ("", False)


# ── The checked wrapper ───────────────────────────────────────────────────────

def test_a_resolved_value_comes_back_with_no_error(monkeypatch):
    monkeypatch.setenv("SD_PASSWORD", "secret_sauce")
    step = StepConfig(action="fill", input_value="ENV:SD_PASSWORD")

    value, error = _checked_input_value(step)

    assert value == "secret_sauce"
    assert error is None


def test_a_missing_env_var_fails_the_step_instead_of_typing_nothing(monkeypatch):
    """
    Filling "" would submit a blank password and surface as a login failure
    somewhere else entirely. This turns it into a named error at the step that
    caused it.
    """
    monkeypatch.delenv("SD_PASSWORD", raising=False)
    step = StepConfig(action="fill", input_value="ENV:SD_PASSWORD")

    value, error = _checked_input_value(step)

    assert value == ""
    assert error is not None
    assert error.status == "failed"
    assert "SD_PASSWORD" in error.error, "the error must name the variable that is missing"


def test_the_failure_names_the_step_it_came_from(monkeypatch):
    monkeypatch.delenv("MISSING", raising=False)
    step = StepConfig(action="fill", description="fill the password field",
                      input_value="ENV:MISSING")

    _value, error = _checked_input_value(step)

    assert error is not None
    assert error.step is step


def test_a_deliberately_empty_literal_is_not_an_error():
    """
    Clearing a field is a legitimate thing for a step to do. Only an *env*
    reference that resolved to nothing is a failure.
    """
    value, error = _checked_input_value(StepConfig(action="fill", input_value=""))

    assert value == ""
    assert error is None


def test_a_plain_value_is_never_checked_against_the_environment():
    value, error = _checked_input_value(StepConfig(action="fill", input_value="Dune"))

    assert (value, error) == ("Dune", None)


# ── Fetching an attribute ─────────────────────────────────────────────────────

async def test_inner_text_is_stripped():
    locator = MagicMock()
    locator.inner_text = AsyncMock(return_value="  Dune  \n")

    assert await _fetch_attr(locator, "innerText") == "Dune"


async def test_inner_html_is_returned_verbatim():
    """Whitespace is meaningful in markup; stripping it would corrupt it."""
    locator = MagicMock()
    locator.inner_html = AsyncMock(return_value="  <b>Dune</b>  ")

    assert await _fetch_attr(locator, "innerHTML") == "  <b>Dune</b>  "


async def test_text_content_is_stripped_and_survives_being_none():
    locator = MagicMock()
    locator.text_content = AsyncMock(return_value=None)

    assert await _fetch_attr(locator, "textContent") == ""


async def test_any_other_name_is_read_as_a_dom_attribute():
    locator = MagicMock()
    locator.get_attribute = AsyncMock(return_value="/book/123")

    assert await _fetch_attr(locator, "href") == "/book/123"
    locator.get_attribute.assert_awaited_once_with("href")


async def test_a_missing_attribute_is_an_empty_string_not_none():
    """
    Callers put this straight into extracted rows. None would serialise as null
    and break a downstream string comparison rather than simply not matching.
    """
    locator = MagicMock()
    locator.get_attribute = AsyncMock(return_value=None)

    assert await _fetch_attr(locator, "data-missing") == ""


# ── Waiting ───────────────────────────────────────────────────────────────────

async def test_a_path_like_target_waits_on_the_url():
    """`/inventory.html` is a destination, not a selector."""
    page = MagicMock()
    page.wait_for_url = AsyncMock()
    page.wait_for_selector = AsyncMock()

    await _wait_for(page, "/inventory.html")

    assert page.wait_for_url.await_count == 1
    assert page.wait_for_selector.await_count == 0


async def test_an_xpath_is_treated_as_a_selector_despite_its_slashes():
    """`//button` starts with a slash but is emphatically not a URL."""
    page = MagicMock()
    page.wait_for_url = AsyncMock()
    page.wait_for_selector = AsyncMock()

    await _wait_for(page, "//button[@id='go']")

    assert page.wait_for_selector.await_count == 1
    assert page.wait_for_url.await_count == 0


async def test_a_css_selector_waits_on_the_selector():
    page = MagicMock()
    page.wait_for_url = AsyncMock()
    page.wait_for_selector = AsyncMock()

    await _wait_for(page, ".inventory_list")

    assert page.wait_for_selector.await_count == 1


async def test_a_timeout_degrades_to_a_sleep_rather_than_raising(monkeypatch):
    """
    wait_for is a hint, not an assertion — the step's own action decides whether
    things worked. Raising here would fail steps whose wait_for was merely
    optimistic.
    """
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("stepper.engine.actions._common.asyncio.sleep", fake_sleep)
    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=TimeoutError("10s exceeded"))

    await _wait_for(page, ".never-appears")   # must not raise

    assert slept, "a failed wait should still pause before carrying on"
