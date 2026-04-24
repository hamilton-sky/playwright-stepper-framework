from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.resolvers.strategies import (
    TextResolver, RoleResolver, PlaceholderResolver,
    IdResolver, CssResolver, XPathResolver, LabelResolver,
)


def _loc(items: list):
    """Return a mock locator whose .all() yields items."""
    loc = MagicMock()
    loc.all = AsyncMock(return_value=items)
    return loc


def _page(**method_results):
    """Build a mock page where each key is a page method and value is its return_value."""
    page = MagicMock()
    for method, result in method_results.items():
        getattr(page, method).return_value = result
    return page


SENTINEL = object()


# ── TextResolver ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_empty_cfg():
    page = MagicMock()
    assert await TextResolver().collect(page, {}) == []
    page.get_by_text.assert_not_called()


@pytest.mark.asyncio
async def test_text_no_match():
    page = _page(get_by_text=_loc([]))
    assert await TextResolver().collect(page, {"text": "Submit"}) == []


@pytest.mark.asyncio
async def test_text_one_match():
    page = _page(get_by_text=_loc([SENTINEL]))
    assert await TextResolver().collect(page, {"text": "Submit"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_text_exception_swallowed():
    page = MagicMock()
    page.get_by_text.side_effect = Exception("boom")
    assert await TextResolver().collect(page, {"text": "Submit"}) == []


@pytest.mark.asyncio
async def test_text_exact_false_passed_through():
    loc = _loc([])
    page = _page(get_by_text=loc)
    await TextResolver().collect(page, {"text": "Submit", "exact": False})
    page.get_by_text.assert_called_once_with("Submit", exact=False)


# ── RoleResolver ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_role_empty_cfg():
    page = MagicMock()
    assert await RoleResolver().collect(page, {}) == []
    page.get_by_role.assert_not_called()


@pytest.mark.asyncio
async def test_role_no_match():
    page = _page(get_by_role=_loc([]))
    assert await RoleResolver().collect(page, {"role": "button"}) == []


@pytest.mark.asyncio
async def test_role_one_match():
    page = _page(get_by_role=_loc([SENTINEL]))
    assert await RoleResolver().collect(page, {"role": "button", "name": "Submit"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_role_exception_swallowed():
    page = MagicMock()
    page.get_by_role.side_effect = Exception("boom")
    assert await RoleResolver().collect(page, {"role": "button"}) == []


@pytest.mark.asyncio
async def test_role_no_name_no_kwargs():
    loc = _loc([])
    page = _page(get_by_role=loc)
    await RoleResolver().collect(page, {"role": "button"})
    call_kwargs = page.get_by_role.call_args[1]
    assert "name" not in call_kwargs


@pytest.mark.asyncio
async def test_role_label_used_as_name():
    loc = _loc([])
    page = _page(get_by_role=loc)
    await RoleResolver().collect(page, {"role": "button", "label": "Submit"})
    assert page.get_by_role.call_args[1].get("name") == "Submit"


# ── PlaceholderResolver ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_placeholder_empty_cfg():
    page = MagicMock()
    assert await PlaceholderResolver().collect(page, {}) == []


@pytest.mark.asyncio
async def test_placeholder_no_match():
    page = _page(get_by_placeholder=_loc([]))
    assert await PlaceholderResolver().collect(page, {"placeholder": "Search..."}) == []


@pytest.mark.asyncio
async def test_placeholder_one_match():
    page = _page(get_by_placeholder=_loc([SENTINEL]))
    assert await PlaceholderResolver().collect(page, {"placeholder": "Search..."}) == [SENTINEL]


@pytest.mark.asyncio
async def test_placeholder_exception_swallowed():
    page = MagicMock()
    page.get_by_placeholder.side_effect = Exception("boom")
    assert await PlaceholderResolver().collect(page, {"placeholder": "x"}) == []


# ── IdResolver ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_id_empty_cfg():
    page = MagicMock()
    assert await IdResolver().collect(page, {}) == []


@pytest.mark.asyncio
async def test_id_no_match():
    page = _page(locator=_loc([]))
    assert await IdResolver().collect(page, {"id": "submit-btn"}) == []


@pytest.mark.asyncio
async def test_id_one_match():
    page = _page(locator=_loc([SENTINEL]))
    assert await IdResolver().collect(page, {"id": "submit-btn"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_id_selector_format():
    loc = _loc([])
    page = _page(locator=loc)
    await IdResolver().collect(page, {"id": "my-id"})
    page.locator.assert_called_once_with("#my-id")


@pytest.mark.asyncio
async def test_id_exception_swallowed():
    page = MagicMock()
    page.locator.side_effect = Exception("boom")
    assert await IdResolver().collect(page, {"id": "x"}) == []


# ── CssResolver ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_css_empty_cfg():
    page = MagicMock()
    assert await CssResolver().collect(page, {}) == []


@pytest.mark.asyncio
async def test_css_no_match():
    page = _page(locator=_loc([]))
    assert await CssResolver().collect(page, {"css": ".btn"}) == []


@pytest.mark.asyncio
async def test_css_one_match():
    page = _page(locator=_loc([SENTINEL]))
    assert await CssResolver().collect(page, {"css": ".btn"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_css_passes_selector_verbatim():
    loc = _loc([])
    page = _page(locator=loc)
    await CssResolver().collect(page, {"css": ".my-class > span"})
    page.locator.assert_called_once_with(".my-class > span")


@pytest.mark.asyncio
async def test_css_exception_swallowed():
    page = MagicMock()
    page.locator.side_effect = Exception("boom")
    assert await CssResolver().collect(page, {"css": ".x"}) == []


# ── XPathResolver ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_xpath_empty_cfg():
    page = MagicMock()
    assert await XPathResolver().collect(page, {}) == []


@pytest.mark.asyncio
async def test_xpath_no_match():
    page = _page(locator=_loc([]))
    assert await XPathResolver().collect(page, {"xpath": "//div"}) == []


@pytest.mark.asyncio
async def test_xpath_one_match():
    page = _page(locator=_loc([SENTINEL]))
    assert await XPathResolver().collect(page, {"xpath": "//div"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_xpath_selector_format():
    loc = _loc([])
    page = _page(locator=loc)
    await XPathResolver().collect(page, {"xpath": "//div[@id='main']"})
    page.locator.assert_called_once_with("xpath=//div[@id='main']")


@pytest.mark.asyncio
async def test_xpath_exception_swallowed():
    page = MagicMock()
    page.locator.side_effect = Exception("boom")
    assert await XPathResolver().collect(page, {"xpath": "//div"}) == []


# ── LabelResolver ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_label_empty_cfg():
    page = MagicMock()
    assert await LabelResolver().collect(page, {}) == []


@pytest.mark.asyncio
async def test_label_no_match():
    page = _page(get_by_label=_loc([]))
    assert await LabelResolver().collect(page, {"label": "Username"}) == []


@pytest.mark.asyncio
async def test_label_one_match():
    page = _page(get_by_label=_loc([SENTINEL]))
    assert await LabelResolver().collect(page, {"label": "Username"}) == [SENTINEL]


@pytest.mark.asyncio
async def test_label_exception_swallowed():
    page = MagicMock()
    page.get_by_label.side_effect = Exception("boom")
    assert await LabelResolver().collect(page, {"label": "Username"}) == []
