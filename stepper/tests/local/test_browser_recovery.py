"""Real Chromium + local HTML: no external site, credentials, models, or AI.

The resolver's semantic/AI fallback and the healer's proposal are controlled;
DOM lookup, interaction, recovery execution and postconditions are real.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from engine.actions.factory import build_default_registry
from engine.healer.healing_cache import HealCache
from engine.interfaces import StepConfig, ResolveResult
from engine.resolvers.element_resolver import ElementResolver
from engine.resolvers.strategies import CssResolver
from engine.runner.step_runner import StepRunner


@pytest_asyncio.fixture
async def local_page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content('''
            <button id="submit" onclick="document.querySelector('#result').textContent='Done'">Submit</button>
            <button id="wrong">Other</button>
            <div id="result">Waiting</div>
        ''')
        yield page
        await browser.close()


def resolver():
    instance = ElementResolver([CssResolver()])
    instance._zero_selector_path = AsyncMock(return_value=ResolveResult(False, method="test-no-fallback"))
    return instance


def runner(page, **kwargs):
    return StepRunner(page, build_default_registry(), resolver(), MagicMock(),
                      behaviour=MagicMock(inter_step_delay=AsyncMock()), **kwargs)


def original():
    return StepConfig(action="click", description="submit", element={"css": "#old-submit"},
                      heal_assert={"element_text_contains": {"selector": "#result", "text": "Done"}})


async def test_missing_element_hard_stops(local_page):
    results, ctx = await runner(local_page).run([
        original(), StepConfig(action="store", description="must not run", extra={"key": "ran", "value": True})
    ])
    assert [r.status for r in results] == ["failed"]
    assert ctx.get("ran") is None
    assert await local_page.locator("#result").inner_text() == "Waiting"


@pytest.mark.parametrize("cached_selector,expected", [("#submit", "healed"), ("#wrong", "failed")])
async def test_cached_heal_checks_actual_dom(local_page, tmp_path, monkeypatch, cached_selector, expected):
    cache = HealCache(tmp_path / "cache.json")
    cache.put(original(), {"css": cached_selector})
    monkeypatch.setattr("engine.runner.step_runner.VisualBridge.check", AsyncMock(return_value="missing"))
    monkeypatch.setattr("engine.runner.step_runner.DOMSnapshotCascade.capture", AsyncMock(return_value={}))
    results, _ = await runner(local_page, cache=cache,
                              healer=MagicMock(heal=AsyncMock(return_value=[])), max_heal_attempts=1).run([original()])
    assert results[0].status == expected
    assert await local_page.locator("#result").inner_text() == ("Done" if expected == "healed" else "Waiting")


async def test_cascade_repair_completes_original_postcondition(local_page, monkeypatch):
    monkeypatch.setattr("engine.runner.step_runner.VisualBridge.check", AsyncMock(return_value="missing"))
    monkeypatch.setattr("engine.runner.step_runner.DOMSnapshotCascade.capture", AsyncMock(return_value={}))
    replacement = StepConfig(action="click", description="submit", element={"css": "#submit"})
    results, _ = await runner(local_page, healer=MagicMock(heal=AsyncMock(return_value=[replacement])),
                              max_heal_attempts=1).run([original()])
    assert results[0].status == "healed"
    assert await local_page.locator("#result").inner_text() == "Done"


async def test_ai_outage_leaves_ambiguous_buttons_untouched(local_page):
    instance = ElementResolver([CssResolver()])
    instance._semantic.score = lambda *args: .9
    instance._ai_pick_resolver.pick = AsyncMock(return_value=None)
    result = await instance.resolve(local_page, {"css": "button"}, "submit")
    assert not result.found
    assert await local_page.locator("#result").inner_text() == "Waiting"
