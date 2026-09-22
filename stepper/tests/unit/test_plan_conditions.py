"""
`when` conditions come from every domain the plan uses, not just the primary.

M3 tagged each condition with the domain whose session it needs and taught
`ConditionRegistry.evaluate` to look that domain up in the run's SessionSet.
M2 built the SessionSet. What was never written was the *merge*: `main.py`
composed the run's vocabulary as `get_domain(cfg.domain).conditions()`, so only
the primary domain's conditions existed.

Nothing noticed for three tickets because the browser was the only domain with
conditions to tag. The moment a second one had some, a mixed workflow was
rejected at plan time:

    FAIL  db_web_mixed
      Step 7 (web: confirm, but only once the database agrees):
        unknown when-condition 'db_row_exists'

M5's `plan_domains` is what makes the fix possible — it already answers which
domains a plan uses, so the merge has a definition.
"""
from __future__ import annotations

import pytest

from stepper.bootstrap.session import Domain, get_domain
from stepper.engine.interfaces import ExecutionContext, StepConfig
from stepper.engine.runner.when_eval import ConditionRegistry, core_conditions
from stepper.engine.session import NullSession, SessionSet


async def _always(session, spec, context):
    return True


class _Action:
    def __init__(self, domain):
        self.domain = domain


class _Registry:
    def __init__(self, **domains):
        self._actions = {n: _Action(d) for n, d in domains.items()}

    def names(self):
        return sorted(self._actions)

    def create(self, name):
        return self._actions[name]


def _step(action) -> StepConfig:
    return StepConfig(action=action, description="x")


def _cfg():
    """A RunConfig with a primary domain of "web" and no workflow to read."""
    import stepper.main as main
    return main.RunConfig(task="a plan under test")


# ── The merge ─────────────────────────────────────────────────────────────────

def test_a_second_domain_s_conditions_are_available(monkeypatch):
    """The bug: a db-tagged clause in a run whose primary domain is the web."""
    import stepper.main as main

    domains = {
        "web": Domain(name="web", session=NullSession,
                      conditions=lambda: core_conditions().register(
                          "url_contains", _always, domain="web")),
        "db":  Domain(name="db", session=NullSession,
                      conditions=lambda: core_conditions().register(
                          "db_row_exists", _always, domain="db")),
    }
    monkeypatch.setattr(main, "get_domain", domains.__getitem__)

    merged = main.plan_conditions(
        _cfg(),
        [_step("navigate"), _step("db_query")],
        _Registry(navigate="web", db_query="db"),
    )

    assert "db_row_exists" in merged
    assert "url_contains" in merged
    assert merged.domain_of("db_row_exists") == "db"


def test_the_core_predicates_survive_the_merge(monkeypatch):
    import stepper.main as main
    monkeypatch.setattr(main, "get_domain", lambda n: Domain(
        name=n, session=NullSession, conditions=core_conditions))

    merged = main.plan_conditions(_cfg(),
                                  [_step("noop_set")], _Registry(noop_set="noop"))

    assert "context_greater_than" in merged
    assert merged.domain_of("context_greater_than") is None


def test_a_domain_the_plan_never_touches_stays_unknown(monkeypatch):
    """
    Merging every *registered* domain would make a typo resolve into some other
    domain's vocabulary and take the did-you-mean with it.
    """
    import stepper.main as main

    domains = {
        "web": Domain(name="web", session=NullSession, conditions=core_conditions),
        "db":  Domain(name="db", session=NullSession,
                      conditions=lambda: core_conditions().register(
                          "db_row_exists", _always, domain="db")),
    }
    monkeypatch.setattr(main, "get_domain", domains.__getitem__)

    merged = main.plan_conditions(_cfg(),
                                  [_step("navigate")], _Registry(navigate="web"))

    assert "db_row_exists" not in merged


# ── The collision guard ───────────────────────────────────────────────────────

def test_two_domains_cannot_claim_one_condition_name():
    """
    Last-wins would mean a `when` clause silently asking the wrong session —
    the same failure ActionRegistry.register refuses for action names.
    """
    first  = core_conditions().register("row_exists", _always, domain="db")
    second = core_conditions().register("row_exists", _always, domain="aws")

    with pytest.raises(ValueError, match="already registered to domain"):
        first.extend(second)


def test_merging_the_same_evaluator_twice_is_fine():
    """
    Every domain's registry starts from core_conditions(), so any merge of two
    of them re-adds the core predicates. That must not be a collision.
    """
    a = core_conditions().register("row_exists", _always, domain="db")
    b = core_conditions().register("row_exists", _always, domain="db")

    a.extend(b)

    assert a.domain_of("row_exists") == "db"


# ── The shipped domains, for real ─────────────────────────────────────────────

def test_the_real_db_and_web_vocabularies_merge(registered_sites):
    """Not doubles: the vocabularies the shipped web and db domains actually ship."""
    import stepper.main as main

    merged = main.plan_conditions(
        _cfg(), [_step("navigate"), _step("db_query")], registered_sites,
    )

    assert {"db_row_exists", "url_contains", "element_exists"} <= set(merged.names())


def _real_registry():
    from stepper.bootstrap.infra import register_all_sites
    from stepper.engine.actions.factory import build_default_registry
    import stepper.main as main

    registry = build_default_registry()
    register_all_sites(registry, main._stepper_root)
    return registry


@pytest.fixture
def registered_sites():
    """
    A real registry with every site registered — which is also what registers
    every Domain, since a domain declares itself from its own register.py.
    """
    return _real_registry()


# ── Routing, once merged ──────────────────────────────────────────────────────

async def test_a_merged_condition_is_evaluated_against_its_own_session():
    """
    The payoff: a db condition in a web-primary run gets the db session, not
    the page. M3 built this; until the merge nothing could reach it.
    """
    seen = {}

    async def records(session, spec, context):
        seen["session"] = session
        return True

    registry = core_conditions().register("db_row_exists", records, domain="db")
    web, db  = object(), object()
    sessions = SessionSet.of("db", _Opened(db))
    sessions.adopt("web", _Opened(web), web)

    result = await registry.evaluate({"db_row_exists": {}}, ExecutionContext(), sessions)

    assert result is True
    assert seen["session"] is db, "a db condition must not be handed the page"


class _Opened:
    """A SessionAdapter double that hands back an object someone else made."""

    def __init__(self, handle):
        self._handle = handle

    async def open(self):
        return self._handle

    async def close(self):
        return None
