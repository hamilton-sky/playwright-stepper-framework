"""
Dispatchers route their sub-steps by domain (ticket M4).

for_each_item and ensure_login forwarded whatever session the parent was
handed, so a sub-step from another domain got the parent's session — the same
defect M1/M2 fixed for top-level steps, one level down. parallel is the
awkward one: both its modes hand each sub-step a browser page, so a sub-step
from another domain has no use for one and `tabs` mode would reach for
page.context on a session that has none.

See docs/mixed-domain-plan.md §4.5.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.actions.flow import (
    EnsureLoginAction, ForEachItemAction, ParallelAction,
)
from stepper.engine.actions.sub_step_mixin import SubStepRunnerMixin
from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.session import SessionSet


class _Recorder(ActionStrategy):
    action_name = "rec"

    def __init__(self, domain, read_only=True):
        self.domain, self.read_only, self.seen = domain, read_only, []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.seen.append(page)
        return StepResult(step=step, status="passed")


class _Factory(ActionFactory):
    def __init__(self, mapping): self._m = mapping
    def create(self, name):
        if name not in self._m:
            raise ValueError(f"Unknown action: '{name}'")
        return self._m[name]


class _Adapter:
    def __init__(self, name): self.domain = name
    async def open(self): return f"{self.domain}-session"
    async def close(self): return None


def _sessions():
    return SessionSet({n: _Adapter(n) for n in ("web", "db")}, primary="web")


# ── for_each_item and ensure_login ────────────────────────────────────────────

async def test_each_sub_step_gets_its_own_domains_session():
    web, db = _Recorder("web"), _Recorder("db")
    host = ForEachItemAction(action_factory=_Factory({"w": web, "d": db}))
    host.set_sessions(_sessions())

    await host._run_sub_steps(
        [{"action": "w", "description": "web sub"},
         {"action": "d", "description": "db sub"}],
        "THE-PARENT-SESSION", MagicMock(), ExecutionContext(),
    )

    assert web.seen == ["web-session"]
    assert db.seen == ["db-session"]


async def test_a_session_agnostic_sub_step_gets_nothing():
    agnostic = _Recorder(None)
    host = ForEachItemAction(action_factory=_Factory({"n": agnostic}))
    host.set_sessions(_sessions())

    await host._run_sub_steps([{"action": "n", "description": "agnostic sub"}],
                              "THE-PARENT-SESSION", MagicMock(), ExecutionContext())

    assert agnostic.seen == [None]


async def test_a_sub_step_result_records_its_domain():
    host = ForEachItemAction(action_factory=_Factory({"d": _Recorder("db")}))
    host.set_sessions(_sessions())

    results = await host._run_sub_steps([{"action": "d", "description": "db sub"}],
                                        None, MagicMock(), ExecutionContext())

    assert results[0].domain == "db"


async def test_without_a_set_the_parent_session_is_forwarded():
    """
    Pre-routing behaviour, for a direct caller or a test double that never
    late-bound a set.
    """
    web = _Recorder("web")
    host = ForEachItemAction(action_factory=_Factory({"w": web}))

    await host._run_sub_steps([{"action": "w", "description": "sub"}],
                              "THE-PARENT-SESSION", MagicMock(), ExecutionContext())

    assert web.seen == ["THE-PARENT-SESSION"]


async def test_ensure_login_routes_the_same_way():
    """Both mixin hosts, not just the one the test above happens to use."""
    db = _Recorder("db")
    host = EnsureLoginAction(action_factory=_Factory({"d": db}))
    host.set_sessions(_sessions())

    await host._run_sub_steps([{"action": "d", "description": "db sub"}],
                              "THE-PARENT-SESSION", MagicMock(), ExecutionContext())

    assert db.seen == ["db-session"]


def test_set_sessions_is_fluent_like_set_conditions():
    host = ForEachItemAction(action_factory=_Factory({}))

    assert host.set_sessions(_sessions()) is host


def test_both_mixin_hosts_are_reachable_from_the_registry():
    """
    build_pipeline finds dispatchers by isinstance, so anything that dispatches
    sub-steps has to actually be a SubStepRunnerMixin or it silently keeps the
    parent's session.
    """
    assert issubclass(ForEachItemAction, SubStepRunnerMixin)
    assert issubclass(EnsureLoginAction, SubStepRunnerMixin)


# ── parallel refuses a foreign domain ─────────────────────────────────────────

def _parallel(mapping):
    return ParallelAction(action_factory=_Factory(mapping))


async def _run(action, sub_steps, mode="tabs", page=None):
    step = StepConfig(action="parallel", description="p",
                      extra={"mode": mode, "steps": sub_steps})
    return await action._execute(page or MagicMock(), step, MagicMock(),
                                 ExecutionContext())


async def test_a_foreign_domain_sub_step_fails_the_whole_step():
    action = _parallel({"w": _Recorder("web"), "d": _Recorder("db")})

    result = await _run(action, [{"action": "w", "description": "a"},
                                 {"action": "d", "description": "b"}])

    assert result.status == "failed"
    assert "must be web actions" in result.error
    assert "domain=db" in result.error


async def test_the_refusal_names_every_offender():
    action = _parallel({"d": _Recorder("db"), "x": _Recorder("aws")})

    result = await _run(action, [{"action": "d", "description": "a"},
                                 {"action": "x", "description": "b"}])

    assert "domain=db" in result.error and "domain=aws" in result.error


async def test_no_sub_step_runs_when_one_is_refused():
    """
    Refusing the whole step, as the write-action gate already does — a parallel
    block that quietly does half its work is worse than one that fails.
    """
    web, db = _Recorder("web"), _Recorder("db")
    action = _parallel({"w": web, "d": db})

    await _run(action, [{"action": "w", "description": "a"},
                        {"action": "d", "description": "b"}])

    assert web.seen == [] and db.seen == []


async def test_the_refusal_applies_to_isolated_browser_mode_too():
    """The gate runs before the mode branch, so both modes are covered."""
    action = _parallel({"d": _Recorder("db")})

    result = await _run(action, [{"action": "d", "description": "a"}],
                        mode="isolated_browser")

    assert result.status == "failed"
    assert "domain=db" in result.error


async def test_a_write_action_is_still_refused_first():
    """The older gate is unchanged and still reported on its own terms."""
    action = _parallel({"w": _Recorder("web", read_only=False)})

    result = await _run(action, [{"action": "w", "description": "a"}])

    assert "write actions not allowed" in result.error


async def test_same_domain_sub_steps_are_allowed():
    page = MagicMock()
    # _run_tabs closes every tab in a finally, so close() must be awaitable.
    tabs = [MagicMock(close=AsyncMock()), MagicMock(close=AsyncMock())]
    page.context.new_page = AsyncMock(side_effect=tabs)
    web = _Recorder("web")
    action = _parallel({"w": web})

    result = await _run(action, [{"action": "w", "description": "a"},
                                 {"action": "w", "description": "b"}], page=page)

    assert result.status == "passed"
    assert web.seen == tabs                 # one tab each, as before


async def test_a_session_agnostic_sub_step_is_allowed_and_gets_none():
    """
    It is harmless in a parallel block — load_test_data reading a file, say —
    and the M1 contract says an action that declared it needs nothing gets
    nothing, tab or no tab.
    """
    page = MagicMock()
    page.context.new_page = AsyncMock(return_value=MagicMock(close=AsyncMock()))
    agnostic = _Recorder(None)
    action = _parallel({"n": agnostic})

    result = await _run(action, [{"action": "n", "description": "a"}], page=page)

    assert result.status == "passed"
    assert agnostic.seen == [None]


async def test_an_unknown_action_is_still_caught_by_the_write_gate():
    action = _parallel({})

    result = await _run(action, [{"action": "nope", "description": "a"}])

    assert result.status == "failed"
    assert "unknown" in result.error
