"""
ExtractDataAction — attribute shapes, filtering, and where the result lands.

This is the action that feeds collected_items to for_each_item and paginate, so
its context routing matters as much as its extraction: writing to the wrong
typed field silently gives the next step nothing to iterate.

No browser — the page is a stub whose locators return canned elements.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.actions.strategies import ExtractDataAction
from engine.interfaces import ExecutionContext, StepConfig


# ── Doubles ───────────────────────────────────────────────────────────────────

def element(inner_text="", attrs=None, inner_html="", text_content=""):
    el = MagicMock()
    el.inner_text    = AsyncMock(return_value=inner_text)
    el.inner_html    = AsyncMock(return_value=inner_html)
    el.text_content  = AsyncMock(return_value=text_content)
    el.get_attribute = AsyncMock(side_effect=lambda name: (attrs or {}).get(name))
    return el


def page_with(elements, selector_found=True):
    page = MagicMock()
    page.wait_for_selector = AsyncMock(
        return_value=True if selector_found else None,
        side_effect=None if selector_found else TimeoutError("no such selector"),
    )
    locator = MagicMock()
    locator.all = AsyncMock(return_value=list(elements))
    page.locator = MagicMock(return_value=locator)
    return page


def extract(page, context=None, **extra):
    step = StepConfig(action="extract_data", description="extract", extra=extra)
    ctx = context or ExecutionContext()
    result = asyncio.run(ExtractDataAction().execute(page, step, MagicMock(), ctx))
    return result, ctx


# ── Required input ────────────────────────────────────────────────────────────

def test_a_missing_selector_fails_with_a_named_field():
    result, _ = extract(page_with([]))

    assert result.status == "failed"
    assert "extra.selector" in result.error


# ── Attribute shapes ──────────────────────────────────────────────────────────

def test_one_attribute_yields_a_flat_list():
    page = page_with([element(inner_text="Dune"), element(inner_text="Foundation")])

    result, ctx = extract(page, selector=".title")

    assert result.status == "passed"
    assert ctx.extracted_data == ["Dune", "Foundation"]


def test_inner_text_is_the_default_attribute():
    page = page_with([element(inner_text="  Dune  ")])

    _, ctx = extract(page, selector=".title")

    assert ctx.extracted_data == ["Dune"]       # and it is stripped


def test_several_attributes_yield_dicts_keyed_by_attribute():
    page = page_with([element(inner_text="Dune", attrs={"href": "/works/OL1W"})])

    _, ctx = extract(page, selector="a", attrs=["innerText", "href"])

    assert ctx.extracted_data == [{"innerText": "Dune", "href": "/works/OL1W"}]


def test_a_missing_attribute_reads_as_empty_string():
    page = page_with([element(attrs={})])

    _, ctx = extract(page, selector="a", attrs=["href"])

    assert ctx.extracted_data == [""]


# ── limit ─────────────────────────────────────────────────────────────────────

def test_limit_caps_the_number_of_items():
    page = page_with([element(inner_text=str(i)) for i in range(10)])

    _, ctx = extract(page, selector=".n", limit=3)

    assert ctx.extracted_data == ["0", "1", "2"]


def test_no_limit_takes_everything():
    page = page_with([element(inner_text=str(i)) for i in range(5)])

    _, ctx = extract(page, selector=".n")

    assert len(ctx.extracted_data) == 5


# ── url_prefix ────────────────────────────────────────────────────────────────

def test_url_prefix_absolutises_relative_hrefs():
    page = page_with([element(attrs={"href": "/works/OL1W"})])

    _, ctx = extract(page, selector="a", attrs=["href"],
                     url_prefix="https://openlibrary.org")

    assert ctx.extracted_data == ["https://openlibrary.org/works/OL1W"]


def test_url_prefix_leaves_absolute_urls_alone():
    page = page_with([element(attrs={"href": "https://elsewhere.test/x"})])

    _, ctx = extract(page, selector="a", attrs=["href"],
                     url_prefix="https://openlibrary.org")

    assert ctx.extracted_data == ["https://elsewhere.test/x"]


def test_a_trailing_slash_on_the_prefix_does_not_double_up():
    page = page_with([element(attrs={"href": "/works/OL1W"})])

    _, ctx = extract(page, selector="a", attrs=["href"],
                     url_prefix="https://openlibrary.org/")

    assert ctx.extracted_data == ["https://openlibrary.org/works/OL1W"]


# ── dedupe ────────────────────────────────────────────────────────────────────

def test_dedupe_removes_repeats_and_keeps_order():
    page = page_with([element(inner_text=t) for t in ("a", "b", "a", "c", "b")])

    _, ctx = extract(page, selector=".t", dedupe=True)

    assert ctx.extracted_data == ["a", "b", "c"]


def test_without_dedupe_repeats_are_kept():
    page = page_with([element(inner_text=t) for t in ("a", "a")])

    _, ctx = extract(page, selector=".t")

    assert ctx.extracted_data == ["a", "a"]


def test_dedupe_is_skipped_for_dict_items():
    """Only scalar lists are deduped; dicts are not hashable."""
    page = page_with([element(inner_text="Dune", attrs={"href": "/a"})] * 2)

    _, ctx = extract(page, selector="a", attrs=["innerText", "href"], dedupe=True)

    assert len(ctx.extracted_data) == 2


# ── Missing selector on the page ──────────────────────────────────────────────

def test_a_selector_that_never_appears_fails_by_default():
    result, _ = extract(page_with([], selector_found=False), selector=".gone")

    assert result.status == "failed"
    assert "extract_data:" in result.error


def test_allow_empty_turns_that_into_a_pass_with_no_items():
    result, ctx = extract(page_with([], selector_found=False),
                          selector=".gone", allow_empty=True)

    assert result.status == "passed"
    assert ctx.extracted_data == []


def test_allow_empty_routes_to_collected_items_when_asked():
    result, ctx = extract(page_with([], selector_found=False), selector=".gone",
                          allow_empty=True, context_key="collected_items")

    assert result.status == "passed"
    assert ctx.collected_items == []


# ── Context routing ───────────────────────────────────────────────────────────

def test_results_land_in_extracted_data_by_default():
    page = page_with([element(inner_text="Dune")])

    _, ctx = extract(page, selector=".t")

    assert ctx.extracted_data == ["Dune"]
    assert ctx.collected_items == []


@pytest.mark.parametrize("key", ["collected_items", "collected_books"])
def test_collected_keys_route_to_the_typed_collected_items_field(key):
    """for_each_item reads collected_items, so both spellings must land there."""
    page = page_with([element(attrs={"href": "/works/OL1W"})])

    _, ctx = extract(page, selector="a", attrs=["href"], context_key=key)

    assert ctx.collected_items == ["/works/OL1W"]
    assert ctx.extracted_data == []


def test_an_unrecognised_context_key_falls_back_to_extracted_data():
    page = page_with([element(inner_text="Dune")])

    _, ctx = extract(page, selector=".t", context_key="something_else")

    assert ctx.extracted_data == ["Dune"]
