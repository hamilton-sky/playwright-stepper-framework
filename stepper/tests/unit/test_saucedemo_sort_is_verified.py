"""
sd_sort_products reported passed for a sort that never happened.

Found the first time the SauceDemo flows ran against local fixtures
(stepper/sites/saucedemo/fixtures/). The action chose an option in the dropdown
and returned passed — whether the product list was then in that order was
never read. A fixture whose list ignored the selection still produced
`sd_sort_products ✓` and `5/5 passed`.

The same shape glue-layer.md names for pt_book_hotel: every interaction landed,
and the fact the step is named for was never checked. Two facts are read now,
and each is pinned here:

  * the dropdown holds the option afterwards (select_sort's return);
  * the products on the page are in that order (is_sorted_by).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import ExecutionContext, StepConfig


def _products(*pairs):
    from poms.saucedemo.pages.inventory_page import ProductSummary
    return [ProductSummary(name=n, price=p) for n, p in pairs]


UNSORTED = (("Sauce Labs Backpack", 29.99), ("Sauce Labs Bike Light", 9.99),
            ("Sauce Labs Onesie", 7.99))


def _inventory_page(products):
    from poms.saucedemo.pages.inventory_page import InventoryPage
    page = InventoryPage(MagicMock(), "http://x", page=None, resolver=None, behaviour=None)
    page.get_all_products = AsyncMock(return_value=_products(*products))
    return page


# ── POM: is_sorted_by reads the list ─────────────────────────────────────────

@pytest.mark.parametrize("option, products, expected", [
    ("lohi", (("b", 1.0), ("a", 2.0), ("c", 2.0)), True),
    ("lohi", UNSORTED, False),
    ("hilo", UNSORTED, True),
    ("az",   (("a", 3.0), ("b", 1.0)), True),
    ("za",   (("a", 3.0), ("b", 1.0)), False),
])
async def test_is_sorted_by_reads_the_order(option, products, expected):
    assert await _inventory_page(products).is_sorted_by(option) is expected


async def test_an_empty_list_is_not_sorted():
    """Nothing on the page is not evidence of anything — least of all an order."""
    assert await _inventory_page(()).is_sorted_by("lohi") is False


async def test_an_unknown_option_is_not_sorted():
    assert await _inventory_page(UNSORTED).is_sorted_by("random") is False


async def test_select_sort_reports_what_the_dropdown_reads():
    from poms.saucedemo.pages.inventory_page import InventoryPage
    driver = MagicMock()
    driver.evaluate = AsyncMock(side_effect=[None, "az"])   # set, then read back
    pom = InventoryPage(driver, "http://x", page=None, resolver=None, behaviour=None)
    assert await pom.select_sort("lohi") is False


# ── Glue: the step fails on either missing fact ──────────────────────────────

def _run(monkeypatch, *, selected: bool, sorted_: bool, option="lohi"):
    from poms.saucedemo.pages.inventory_page import InventoryPage
    from stepper.sites.saucedemo.pages.inventory_action import SDInventoryPage

    monkeypatch.setattr(InventoryPage, "select_sort", AsyncMock(return_value=selected))
    monkeypatch.setattr(InventoryPage, "is_sorted_by", AsyncMock(return_value=sorted_))

    action = SDInventoryPage.SDSortProductsAction()
    action._driver = lambda page: MagicMock()
    step = StepConfig(action="sd_sort_products", description="sort", extra={"sort": option})
    return action.execute(MagicMock(), step, MagicMock(), ExecutionContext())


async def test_the_step_passes_only_when_the_list_is_in_order(monkeypatch):
    result = await _run(monkeypatch, selected=True, sorted_=True)
    assert result.status == "passed"


async def test_a_dropdown_that_did_not_take_the_option_fails(monkeypatch):
    result = await _run(monkeypatch, selected=False, sorted_=True)
    assert result.status == "failed"
    assert "select_sort()" in result.error


async def test_a_list_that_did_not_re_sort_fails(monkeypatch):
    """The regression itself: the dropdown says lohi, the products do not."""
    result = await _run(monkeypatch, selected=True, sorted_=False)
    assert result.status == "failed"
    assert "not in 'lohi' order" in result.error


async def test_an_unknown_sort_is_a_configuration_failure(monkeypatch):
    result = await _run(monkeypatch, selected=True, sorted_=True, option="cheapest")
    assert result.status == "failed"
    assert "unknown sort" in result.error
