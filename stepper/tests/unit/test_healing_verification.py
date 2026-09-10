"""Recovery must do real work and satisfy the original postcondition."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.interfaces import StepConfig, StepResult
from engine.runner.step_runner import StepRunner, _run_heal_assert
from .test_step_runner import ScriptedAction, FakeFactory


@pytest.mark.parametrize("route", ["cache", "cascade", "hidden", "disabled"])
@pytest.mark.parametrize("assert_passes", [True, False])
async def test_all_recovery_routes_verify_postcondition(monkeypatch, route, assert_passes):
    page = MagicMock()
    page.url = "https://example.test/done" if assert_passes else "https://example.test/start"
    page.query_selector = AsyncMock(return_value=None)
    behaviour = MagicMock(inter_step_delay=AsyncMock())
    action = ScriptedAction(["failed", "passed"])
    original = StepConfig(action="scripted", description="submit", heal_assert={"url_contains": "/done"})
    replacement = StepConfig(action="scripted", description="submit")
    healer = MagicMock(heal=AsyncMock(return_value=[replacement]))
    cache = MagicMock(get=MagicMock(return_value={"css": "#fixed"} if route == "cache" else None))
    monkeypatch.setattr("engine.runner.step_runner.VisualBridge.check", AsyncMock(return_value=route))
    monkeypatch.setattr("engine.runner.step_runner.DOMSnapshotCascade.capture", AsyncMock(return_value={}))
    runner = StepRunner(page, FakeFactory({"scripted": action}), MagicMock(), MagicMock(),
                        behaviour=behaviour, healer=healer, max_heal_attempts=1, cache=cache)
    if route in {"hidden", "disabled"}:
        async def inject(*args):
            return StepResult(step=original, status="passed"), args[-1]
        runner._try_inject_pre_step = inject
    results, _ = await runner.run([original])
    assert results[0].status == ("healed" if assert_passes else "failed")
    if not assert_passes:
        cache.put.assert_not_called()


@pytest.mark.parametrize("statuses", [[], ["skipped"], ["warned"], ["passed", "skipped"], ["failed"]])
async def test_noncompletion_never_counts_as_healed(monkeypatch, statuses):
    page = MagicMock(query_selector=AsyncMock(return_value=None))
    behaviour = MagicMock(inter_step_delay=AsyncMock())
    original = StepConfig(action="original", description="original")
    replacements = [StepConfig(action=f"r{i}", description="replacement") for i in range(len(statuses))]
    actions = {"original": ScriptedAction(["failed"])}
    actions.update({f"r{i}": ScriptedAction([status]) for i, status in enumerate(statuses)})
    monkeypatch.setattr("engine.runner.step_runner.VisualBridge.check", AsyncMock(return_value="missing"))
    monkeypatch.setattr("engine.runner.step_runner.DOMSnapshotCascade.capture", AsyncMock(return_value={}))
    runner = StepRunner(page, FakeFactory(actions), MagicMock(), MagicMock(), behaviour=behaviour,
                        healer=MagicMock(heal=AsyncMock(return_value=replacements)), max_heal_attempts=1)
    results, _ = await runner.run([original])
    assert results[0].status == "failed"


@pytest.mark.parametrize("spec", [{}, {"url_contians": "/done"}, {"url_contains": "/done", "typo": True}])
async def test_unknown_or_empty_assertions_fail_closed(spec):
    assert not await _run_heal_assert(MagicMock(url="/done"), spec)
