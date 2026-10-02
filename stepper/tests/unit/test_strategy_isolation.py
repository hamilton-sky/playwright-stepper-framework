"""
A resolver strategy that raises is isolated — and named, not hidden.

`_interact` calls `resolver.resolve()` outside its try, and the cascade used to
call each strategy's `collect()` bare, so one strategy that raised took down the
whole chain: the other strategies never ran and the exception escaped into the
POM. Every shipped strategy catches its own, so this needed a custom one that
does not — which is exactly the case nobody would notice until it shipped.

The fix has two halves, and each is pinned here:

  * the other strategies still get their turn, so a broken one cannot stop a
    healthy one from finding the element;
  * if nothing else finds it, the answer is not-found *naming the strategy that
    raised* — not a fall-through to the keyword-fuzzy match on the description,
    which would turn a broken strategy into a plausible wrong click everywhere.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.resolvers.element_resolver import ElementResolver


@pytest.fixture(autouse=True)
def _allow_building_a_resolver(monkeypatch):
    monkeypatch.setattr(
        "stepper.engine.resolvers.strategies.SemanticResolver.__init__",
        lambda self, *a, **kw: None,
    )


def _strategy(name, priority, *, returns=None, raises=None):
    s = MagicMock()
    s.name = name
    s.priority = priority
    if raises is not None:
        s.collect = AsyncMock(side_effect=raises)
    else:
        s.collect = AsyncMock(return_value=returns or [])
    return s


def _resolver(*strategies):
    r = ElementResolver(list(strategies))
    r._zero_selector_path = AsyncMock(side_effect=AssertionError("fuzzy path reached"))
    r._visual_fallback = AsyncMock(side_effect=AssertionError("visual path reached"))
    return r


async def test_a_raising_strategy_does_not_stop_the_next_one():
    el = object()
    r = _resolver(
        _strategy("role", 10, raises=RuntimeError("boom")),
        _strategy("css", 60, returns=[el]),
    )
    result = await r.resolve(MagicMock(), {"role": "button", "css": ".x"}, "click it")
    assert result.found
    assert result.locator is el
    assert result.method == "css"


async def test_nothing_found_after_a_raise_is_not_found_naming_the_strategy():
    r = _resolver(
        _strategy("role", 10, raises=RuntimeError("boom")),
        _strategy("css", 60, returns=[]),
    )
    result = await r.resolve(MagicMock(), {"role": "button", "css": ".x"}, "click it")
    assert not result.found
    assert result.method == "strategy-error:role"


async def test_the_raise_does_not_escape_resolve():
    r = _resolver(_strategy("css", 60, raises=ValueError("bad selector")))
    result = await r.resolve(MagicMock(), {"css": ".x"}, "click it")
    assert not result.found


async def test_strict_resolution_reports_the_broken_strategy_too():
    r = _resolver(_strategy("css", 60, raises=ValueError("bad selector")))
    result = await r.resolve(MagicMock(), {"css": ".x"}, "check it", strict=True)
    assert not result.found
    assert result.method == "strategy-error:css"


async def test_without_a_raise_the_fuzzy_fallback_still_runs():
    r = ElementResolver([_strategy("css", 60, returns=[])])
    sentinel = MagicMock(found=True)
    r._zero_selector_path = AsyncMock(return_value=sentinel)
    result = await r.resolve(MagicMock(), {"css": ".x"}, "click it")
    assert result is sentinel
