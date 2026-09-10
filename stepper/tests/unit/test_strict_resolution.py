from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.resolvers.element_resolver import ElementResolver
from engine.interfaces import StepConfig, ResolveResult
from engine.actions.strategies import ClickAction, FillAction, HoverAction, SelectAction, ScrollToAction, KeyboardPressAction


async def test_ambiguous_without_description_is_not_resolved():
    resolver = ElementResolver([])
    result = await resolver._semantic_filter([object(), object()], "", "css")
    assert not result.found


@pytest.mark.parametrize("strict,found", [(True, False), (False, True)])
async def test_ai_outage_does_not_guess_unless_legacy_mode_requested(strict, found):
    resolver = ElementResolver([], strict=strict)
    resolver._ai_pick_resolver.pick = AsyncMock(return_value=None)
    result = await resolver._ai_pick([(object(), "first", .91), (object(), "second", .90)], "submit", "css")
    assert result.found is found


async def test_low_confidence_ai_answer_is_rejected():
    resolver = ElementResolver([])
    resolver._ai_pick_resolver.pick = AsyncMock(return_value=(0, .3))
    result = await resolver._ai_pick([(object(), "first", .91)], "submit", "css")
    assert not result.found


@pytest.mark.parametrize("action", [ClickAction, FillAction, HoverAction, SelectAction, ScrollToAction, KeyboardPressAction])
@pytest.mark.parametrize("found,confidence", [(False, 0), (True, .2)])
async def test_unsuccessful_resolution_fails_action(action, found, confidence):
    locator = MagicMock()
    resolver = MagicMock(resolve=AsyncMock(return_value=ResolveResult(found, locator, confidence)))
    step = StepConfig(action=action.action_name, description="test", element={"css": "#missing"}, input_value="Enter")
    result = await action().execute(MagicMock(), step, resolver)
    assert result.status == "failed"
    assert not locator.mock_calls


async def test_public_resolve_cannot_fall_through_after_ai_outage():
    strategy = MagicMock(name="strategy")
    strategy.name = "css"
    strategy.priority = 60
    candidates = [MagicMock(), MagicMock()]
    strategy.collect = AsyncMock(return_value=candidates)
    resolver = ElementResolver([strategy])
    resolver._describe_locator = AsyncMock(return_value="submit")
    resolver._semantic.score = lambda *args: .9
    resolver._ai_pick_resolver.pick = AsyncMock(return_value=None)
    resolver._zero_selector_path = AsyncMock(return_value=ResolveResult(True, candidates[0], .9))
    result = await resolver.resolve(MagicMock(), {"css": "button"}, "submit")
    assert not result.found
    resolver._zero_selector_path.assert_not_called()
