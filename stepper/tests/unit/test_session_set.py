"""
SessionSet — the run's sessions, keyed by domain (ticket M2).

StepRunner used to hold one session and hand it to every action. It now holds
one of these and asks the action which domain it needs. What matters is that
routing works, that opening stays lazy, that closing unwinds in reverse — and
that every existing single-session caller behaves exactly as it did.

See docs/mixed-domain-plan.md §4.2.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, StepConfig, StepResult,
)
from stepper.engine.runner.step_runner import StepRunner
from stepper.engine.session import NullSession, SessionSet, UnknownDomainError


class _Adapter:
    """A SessionAdapter that records its own lifecycle."""

    def __init__(self, name, *, fail_close=False, closed_log=None):
        self.domain, self.opens, self.closes = name, 0, 0
        self._fail_close = fail_close
        self._closed_log = closed_log

    async def open(self):
        self.opens += 1
        return f"{self.domain}-session"

    async def close(self):
        self.closes += 1
        if self._closed_log is not None:
            self._closed_log.append(self.domain)
        if self._fail_close:
            raise RuntimeError(f"{self.domain} close failed")


def _set(*names, primary=None, **kw):
    adapters = {n: _Adapter(n, **kw) for n in names}
    return SessionSet(adapters, primary=primary or names[0]), adapters


# ── Lazy opening ──────────────────────────────────────────────────────────────

async def test_building_a_set_opens_nothing():
    """A db-only workflow must not launch a browser just because web exists."""
    sessions, adapters = _set("web", "db")

    assert sessions.opened_domains() == []
    assert all(a.opens == 0 for a in adapters.values())


async def test_a_domain_opens_on_first_use():
    sessions, adapters = _set("web", "db")

    assert await sessions.get("db") == "db-session"

    assert sessions.opened_domains() == ["db"]
    assert adapters["db"].opens == 1
    assert adapters["web"].opens == 0


async def test_a_second_use_reuses_the_open_session():
    sessions, adapters = _set("web")

    first, second = await sessions.get("web"), await sessions.get("web")

    assert first is second
    assert adapters["web"].opens == 1


async def test_open_order_is_recorded():
    sessions, _ = _set("web", "db", "aws")

    await sessions.get("db")
    await sessions.get("aws")
    await sessions.get("db")          # already open — not recorded twice

    assert sessions.opened_domains() == ["db", "aws"]


# ── The session-agnostic contract ─────────────────────────────────────────────

async def test_a_none_domain_receives_nothing():
    """
    An action that declared it needs no session is handed None, not whichever
    session happened to open first — so an accidental dependency surfaces.
    """
    sessions, adapters = _set("web")

    assert await sessions.get(None) is None
    assert adapters["web"].opens == 0


# ── Unknown domains ───────────────────────────────────────────────────────────

async def test_an_unknown_domain_raises_and_names_itself():
    sessions, _ = _set("web", "db")

    with pytest.raises(UnknownDomainError) as excinfo:
        await sessions.get("aws")

    assert "aws" in str(excinfo.value)
    assert "db" in str(excinfo.value) and "web" in str(excinfo.value)


# ── Closing ───────────────────────────────────────────────────────────────────

async def test_close_all_closes_in_reverse_order():
    """Newest first: a session opened later may depend on an earlier one."""
    closed = []
    sessions = SessionSet(
        {n: _Adapter(n, closed_log=closed) for n in ("web", "db", "aws")},
        primary="web",
    )
    for name in ("web", "db", "aws"):
        await sessions.get(name)

    await sessions.close_all()

    assert closed == ["aws", "db", "web"]


async def test_only_opened_sessions_are_closed():
    sessions, adapters = _set("web", "db")

    await sessions.get("db")
    await sessions.close_all()

    assert adapters["db"].closes == 1
    assert adapters["web"].closes == 0


async def test_a_failure_closing_one_still_closes_the_rest():
    """
    Closing a browser context is what flushes a recorded video and a browser
    left running outlives the process — neither may be skipped because an
    earlier close raised. The first failure still propagates.
    """
    closed = []
    sessions = SessionSet(
        {"web": _Adapter("web", closed_log=closed),
         "db":  _Adapter("db", fail_close=True, closed_log=closed)},
        primary="web",
    )
    await sessions.get("web")
    await sessions.get("db")

    with pytest.raises(RuntimeError, match="db close failed"):
        await sessions.close_all()

    assert closed == ["db", "web"], "web must still close after db raised"


async def test_closing_an_empty_set_is_harmless():
    sessions, _ = _set("web")
    await sessions.close_all()


# ── The legacy single-session mode ────────────────────────────────────────────

async def test_a_single_session_answers_every_domain():
    """
    Exactly how the loop behaved before routing: one object, handed to every
    action whatever it declared. Test doubles and sub-runners rely on it.
    """
    sessions = SessionSet.single("THE-PAGE")

    assert await sessions.get("web") == "THE-PAGE"
    assert await sessions.get("db") == "THE-PAGE"
    assert await sessions.get("anything") == "THE-PAGE"


async def test_a_single_session_still_gives_nothing_for_no_domain():
    assert await SessionSet.single("THE-PAGE").get(None) is None


async def test_a_single_session_set_closes_nothing_it_did_not_open():
    session = MagicMock(close=AsyncMock())

    await SessionSet.single(session).close_all()

    session.close.assert_not_awaited()


async def test_primary_is_the_single_session():
    assert SessionSet.single("THE-PAGE").primary == "THE-PAGE"


async def test_primary_is_the_named_domain_once_open():
    sessions, _ = _set("web", "db", primary="web")

    await sessions.get("db")
    assert sessions.primary is None          # web has not opened yet
    await sessions.get("web")
    assert sessions.primary == "web-session"


async def test_adopt_records_a_session_opened_elsewhere():
    """build_pipeline opens the primary eagerly, then hands it over."""
    adapter = _Adapter("web")
    sessions = SessionSet({}, primary=None)

    sessions.adopt("web", adapter, await adapter.open())

    assert sessions.primary == "web-session"
    assert sessions.opened_domains() == ["web"]
    await sessions.close_all()
    assert adapter.closes == 1


# ── StepRunner routes by the action's domain ──────────────────────────────────

class _Recorder(ActionStrategy):
    action_name = "rec"

    def __init__(self, domain):
        self.domain = domain
        self.seen = []

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.seen.append(page)
        return StepResult(step=step, status="passed")


class _Factory(ActionFactory):
    def __init__(self, mapping): self._m = mapping
    def create(self, name): return self._m[name]


@pytest.fixture
def runner_parts():
    reporter = MagicMock(record_step=MagicMock())
    behaviour = MagicMock(inter_step_delay=AsyncMock(return_value=None))
    return reporter, behaviour


async def test_each_step_gets_its_own_domains_session(runner_parts):
    reporter, behaviour = runner_parts
    web, db = _Recorder("web"), _Recorder("db")
    sessions, _ = _set("web", "db")
    runner = StepRunner(sessions=sessions, action_factory=_Factory({"w": web, "d": db}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    await runner.run([StepConfig(action="w", description="a"),
                      StepConfig(action="d", description="b"),
                      StepConfig(action="w", description="c")])

    assert web.seen == ["web-session", "web-session"]
    assert db.seen == ["db-session"]


async def test_a_session_agnostic_step_is_handed_none(runner_parts):
    reporter, behaviour = runner_parts
    agnostic = _Recorder(None)
    sessions, adapters = _set("web")
    runner = StepRunner(sessions=sessions, action_factory=_Factory({"n": agnostic}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    await runner.run([StepConfig(action="n", description="a")])

    assert agnostic.seen == [None]
    assert adapters["web"].opens == 0        # nothing opened for it


async def test_the_result_records_which_domain_ran(runner_parts):
    reporter, behaviour = runner_parts
    sessions, _ = _set("web", "db")
    runner = StepRunner(sessions=sessions,
                        action_factory=_Factory({"w": _Recorder("web"),
                                                 "d": _Recorder("db"),
                                                 "n": _Recorder(None)}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    results, _ = await runner.run([StepConfig(action="w", description="a"),
                                   StepConfig(action="d", description="b"),
                                   StepConfig(action="n", description="c")])

    assert [r.domain for r in results] == ["web", "db", None]


async def test_an_unknown_domain_fails_the_step_with_its_name(runner_parts):
    reporter, behaviour = runner_parts
    sessions, _ = _set("web")
    runner = StepRunner(sessions=sessions, action_factory=_Factory({"a": _Recorder("aws")}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    results, _ = await runner.run([StepConfig(action="a", description="a")])

    assert results[0].status == "failed"
    assert "aws" in results[0].error


# ── Back-compat: page= and session= are untouched ─────────────────────────────

async def test_page_still_reaches_every_action(runner_parts):
    """The additive promise: a single-session runner behaves exactly as before."""
    reporter, behaviour = runner_parts
    web, db = _Recorder("web"), _Recorder("db")
    runner = StepRunner(page="THE-PAGE", action_factory=_Factory({"w": web, "d": db}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    await runner.run([StepConfig(action="w", description="a"),
                      StepConfig(action="d", description="b")])

    assert web.seen == ["THE-PAGE"]
    assert db.seen == ["THE-PAGE"]           # even a foreign domain, as before


def test_the_primary_still_reads_back_as_page(runner_parts):
    reporter, behaviour = runner_parts
    marker = object()

    runner = StepRunner(session=marker, action_factory=_Factory({}),
                        reporter=reporter, behaviour=behaviour)

    assert runner._page is marker


async def test_sub_runners_inherit_the_whole_set(runner_parts):
    """
    The heal path builds fresh StepRunners. A run's routing has to survive
    that, or a healed step would be handed the wrong session.
    """
    reporter, behaviour = runner_parts
    db = _Recorder("db")
    sessions, _ = _set("web", "db")
    runner = StepRunner(sessions=sessions, action_factory=_Factory({"d": db}),
                        reporter=reporter, behaviour=behaviour, hooks=[])

    from stepper.engine.interfaces import ExecutionContext
    await runner._try_inject_pre_step("d", StepConfig(action="d", description="x"),
                                      ExecutionContext())

    assert db.seen == ["db-session", "db-session"]


async def test_the_noop_domain_session_is_usable_through_a_set():
    sessions = SessionSet({"noop": NullSession("noop")}, primary="noop")

    opened = await sessions.get("noop")

    assert opened is not None
    await sessions.close_all()
