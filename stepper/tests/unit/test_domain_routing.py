"""
Hooks and conditions follow the step's domain (ticket M3).

Before this, every hook ran for every step. In a mixed run that means the web
domain's ScreenshotHook would try to screenshot a database connection — and
ScreenshotHook swallows its own errors, so the result is *silence*, not a
failure. That is the exact mode the universal-runner work existed to remove,
and it is what these tests pin shut.

Conditions move the same way. One `when` may name url_contains and a db
predicate at once, so the registry records each condition's domain and looks
the session up before calling the evaluator — which is why an evaluator's
signature stays (session, spec, context).

See docs/mixed-domain-plan.md §4.3 and §4.4.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.runner.hooks import ScreenshotHook, StepHook
from stepper.engine.runner.step_runner import StepRunner
from stepper.engine.runner.when_eval import (
    ConditionRegistry, UnknownConditionError, core_conditions,
)
from stepper.engine.session import SessionSet


class _Action(ActionStrategy):
    action_name = "act"

    def __init__(self, domain):
        self.domain = domain

    async def _execute(self, page, step, resolver, context, behaviour=None):
        return StepResult(step=step, status="passed")


class _Factory(ActionFactory):
    def __init__(self, mapping): self._m = mapping
    def create(self, name): return self._m[name]


class _Spy(StepHook):
    def __init__(self, label):
        self.label, self.before_saw, self.after_saw = label, [], []

    async def before(self, session, step, idx):
        self.before_saw.append(step.description)

    async def after(self, session, step, result, idx):
        self.after_saw.append(step.description)


class _Adapter:
    def __init__(self, name): self.domain = name
    async def open(self): return f"{self.domain}-session"
    async def close(self): return None


@pytest.fixture
def parts():
    return (MagicMock(record_step=MagicMock()),
            MagicMock(inter_step_delay=AsyncMock(return_value=None)))


def _runner(hooks, mapping, parts, **kw):
    reporter, behaviour = parts
    sessions = SessionSet({n: _Adapter(n) for n in ("web", "db")}, primary="web")
    return StepRunner(sessions=sessions, action_factory=_Factory(mapping),
                      reporter=reporter, behaviour=behaviour, hooks=hooks, **kw)


# ── A step runs its own domain's hooks, and no others ─────────────────────────

async def test_each_step_runs_only_its_own_domains_hooks(parts):
    web, db = _Spy("web"), _Spy("db")
    runner = _runner({"web": [web], "db": [db]},
                     {"w": _Action("web"), "d": _Action("db")}, parts)

    await runner.run([StepConfig(action="w", description="a web step"),
                      StepConfig(action="d", description="a db step")])

    assert web.before_saw == ["a web step"]
    assert db.before_saw == ["a db step"]


async def test_the_same_holds_for_after_hooks(parts):
    web, db = _Spy("web"), _Spy("db")
    runner = _runner({"web": [web], "db": [db]},
                     {"w": _Action("web"), "d": _Action("db")}, parts)

    await runner.run([StepConfig(action="d", description="a db step")])

    assert web.after_saw == []
    assert db.after_saw == ["a db step"]


async def test_the_browser_screenshot_hook_never_sees_a_database_step(parts, tmp_path):
    """
    The bug M3 exists to fix, stated concretely. ScreenshotHook calls
    session.screenshot(...) and swallows whatever comes back, so pointing it at
    a connection produced silence rather than a failure — the worst possible
    outcome for something meant to document a run.
    """
    shot = ScreenshotHook(tmp_path)
    runner = _runner({"web": [shot]}, {"d": _Action("db")}, parts,
                     screenshots_dir=tmp_path)

    results, _ = await runner.run([StepConfig(action="d", description="a db step")])

    assert results[0].status == "passed"
    assert results[0].screenshot == ""          # no attempt was made
    assert list(tmp_path.iterdir()) == []


async def test_a_domain_with_no_hooks_registered_runs_none(parts):
    web = _Spy("web")
    runner = _runner({"web": [web]}, {"d": _Action("db")}, parts)

    await runner.run([StepConfig(action="d", description="a db step")])

    assert web.before_saw == []


# ── Session-agnostic steps ────────────────────────────────────────────────────

async def test_a_session_agnostic_step_runs_no_hooks_by_default(parts):
    web = _Spy("web")
    runner = _runner({"web": [web]}, {"n": _Action(None)}, parts)

    await runner.run([StepConfig(action="n", description="an agnostic step")])

    assert web.before_saw == []


async def test_none_is_a_domain_key_like_any_other(parts):
    """
    Which is why M3 needs no separate "global hooks" rule: hooks for
    session-agnostic steps go under None, and the dispatch rule stays one
    sentence — a step runs its own domain's hooks.
    """
    agnostic = _Spy("agnostic")
    runner = _runner({None: [agnostic]}, {"n": _Action(None)}, parts)

    await runner.run([StepConfig(action="n", description="an agnostic step")])

    assert agnostic.before_saw == ["an agnostic step"]


# ── The shape itself ──────────────────────────────────────────────────────────

def test_hooks_default_to_an_empty_mapping(parts):
    reporter, behaviour = parts

    runner = StepRunner(page=MagicMock(), action_factory=_Factory({}),
                        reporter=reporter, behaviour=behaviour)

    assert runner._hooks == {}


def test_a_flat_list_is_rejected(parts):
    """
    Dict only, deliberately. A list meaning "every step" is precisely the
    defect this ticket removes, so accepting one would keep the footgun in the
    API for the sake of callers that no longer exist.
    """
    reporter, behaviour = parts

    with pytest.raises(AttributeError):
        StepRunner(page=MagicMock(), action_factory=_Factory({}),
                   reporter=reporter, behaviour=behaviour, hooks=[_Spy("x")])


# ── Conditions carry a domain too ─────────────────────────────────────────────

async def test_a_condition_is_handed_its_own_domains_session():
    seen = {}

    async def web_cond(session, spec, context):
        seen["web"] = session
        return True

    async def db_cond(session, spec, context):
        seen["db"] = session
        return True

    registry = (core_conditions()
                .register("on_page", web_cond, domain="web")
                .register("in_table", db_cond, domain="db"))
    sessions = SessionSet({n: _Adapter(n) for n in ("web", "db")}, primary="web")

    await registry.evaluate({"all": [{"on_page": 1}, {"in_table": 2}]},
                            ExecutionContext(), sessions)

    assert seen == {"web": "web-session", "db": "db-session"}


async def test_a_core_predicate_is_handed_nothing():
    """It reads the ExecutionContext; a session would only be something to misuse."""
    seen = []

    async def spy(session, spec, context):
        seen.append(session)
        return True

    registry = core_conditions().register("probe", spy)      # no domain
    sessions = SessionSet({"web": _Adapter("web")}, primary="web")

    await registry.evaluate({"probe": 1}, ExecutionContext(), sessions)

    assert seen == [None]


def test_the_web_conditions_declare_their_domain():
    from stepper.engine.browser.conditions import web_conditions

    registry = web_conditions()

    assert registry.domain_of("url_contains") == "web"
    assert registry.domain_of("element_exists") == "web"
    assert registry.domain_of("context_equals") is None


async def test_a_bare_session_still_works_for_a_domain_condition():
    """
    A caller holding one object — a test, or sub-step dispatch before M4 —
    passes it straight in and every condition sees it.
    """
    from stepper.engine.browser.conditions import web_conditions

    page = MagicMock(url="https://example.test/receipt")

    assert await web_conditions().evaluate({"url_contains": "/receipt"},
                                           ExecutionContext(), page)


async def test_an_unknown_condition_still_raises():
    with pytest.raises(UnknownConditionError):
        await core_conditions().evaluate({"nonsense": 1}, ExecutionContext(), None)


async def test_a_combinator_passes_the_sessions_down_not_a_session():
    """`not`/`all`/`any` recurse, so the set has to survive the recursion."""
    seen = []

    async def spy(session, spec, context):
        seen.append(session)
        return False

    registry = core_conditions().register("probe", spy, domain="web")
    sessions = SessionSet({"web": _Adapter("web")}, primary="web")

    assert await registry.evaluate({"not": {"probe": 1}}, ExecutionContext(), sessions)
    assert seen == ["web-session"]
