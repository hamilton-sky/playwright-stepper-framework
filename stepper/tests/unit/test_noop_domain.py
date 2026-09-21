"""
The receipt for docs/universal-runner-plan.md.

The whole plan reduces to one claim: StepRunner runs steps, and "browser" is
one domain among several rather than the thing the engine is built out of.
`stepper/sites/_noop/` is a domain with no session worth opening, no hooks, no
resolver and no POMs, and these tests try to falsify the claim against it.

The load-bearing one is test_a_noop_run_never_imports_playwright. It runs in a
subprocess on purpose: pytest shares one interpreter across the whole suite,
and test_anti_detection legitimately imports playwright, so an in-process
`"playwright" not in sys.modules` would pass or fail on test ordering. A fresh
process is the only honest way to ask the question.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from stepper.bootstrap.session import get_domain
from stepper.engine.interfaces import ExecutionContext, StepConfig
from stepper.engine.resolvers.null_resolver import NullResolver
from stepper.engine.runner.step_runner import StepRunner
from stepper.engine.session import NullSession, SessionAdapter
from stepper.sites._noop.register import NOOP_DOMAIN

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW  = _REPO_ROOT / "stepper" / "sites" / "_noop" / "workflows" / "noop_smoke.json"


# ── The receipt ───────────────────────────────────────────────────────────────

def test_a_noop_run_never_imports_playwright():
    """
    A workflow of non-browser steps runs to completion — reporting, `when` and
    context flow included — and Playwright is never imported.

    This is the sentence §1 of the plan is written around. It was impossible
    to even ask before T7: build_action_registry pulled Playwright in through
    poms/shared/driver.py (L9), and the tests' own conftest imported it at
    module scope (L10).
    """
    script = textwrap.dedent(f"""
        import asyncio, sys
        sys.path.insert(0, {str(_REPO_ROOT)!r})
        from stepper.main import run

        results = asyncio.run(run(workflow_path={str(_WORKFLOW)!r}))
        leaked  = sorted(m for m in sys.modules if m.split(".")[0] == "playwright")
        print("STATUSES:" + ",".join(r.status for r in results))
        print("PLAYWRIGHT:" + ",".join(leaked))
    """)

    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=300)

    assert proc.returncode == 0, f"the noop run failed:\n{proc.stderr[-3000:]}"
    statuses = next(l for l in proc.stdout.splitlines() if l.startswith("STATUSES:"))
    leaked   = next(l for l in proc.stdout.splitlines() if l.startswith("PLAYWRIGHT:"))

    assert statuses == "STATUSES:passed,passed,skipped"
    assert leaked == "PLAYWRIGHT:", f"a browser-free run imported Playwright: {leaked}"


def test_validate_opens_nothing_and_imports_nothing():
    """The same claim for the path that was already meant to be browser-free."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(_REPO_ROOT)!r})
        from stepper.main import validate_plan, RunConfig

        validate_plan(RunConfig(workflow_path={str(_WORKFLOW)!r}))
        leaked = sorted(m for m in sys.modules if m.split(".")[0] == "playwright")
        print("PLAYWRIGHT:" + ",".join(leaked))
    """)

    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=300)

    assert proc.returncode == 0, proc.stderr[-3000:]
    leaked = next(l for l in proc.stdout.splitlines() if l.startswith("PLAYWRIGHT:"))

    assert leaked == "PLAYWRIGHT:", f"validate imported Playwright: {leaked}"


# ── The domain itself ─────────────────────────────────────────────────────────

def test_the_noop_domain_is_discovered_by_the_ordinary_mechanism():
    """
    register_all_sites globs sites/*/register.py. §2 of the plan claimed a new
    domain would need no change to that; this is the claim under test.
    """
    from stepper.bootstrap.infra import register_all_sites
    from stepper.engine.actions.factory import build_default_registry

    registry = build_default_registry()
    register_all_sites(registry, _REPO_ROOT / "stepper")

    assert "noop_set" in registry
    assert "noop_echo" in registry
    assert get_domain("noop") is NOOP_DOMAIN


def test_the_noop_domain_brings_no_hooks():
    assert NOOP_DOMAIN.hooks(None) == []


async def test_the_noop_domain_has_nothing_to_share():
    async with NOOP_DOMAIN.shared(None, None) as shared:
        assert shared is None


async def test_the_noop_session_opens_and_closes():
    session = NOOP_DOMAIN.session(None, None, None, shared=None)

    assert isinstance(session, NullSession)
    assert isinstance(session, SessionAdapter)
    assert await session.open() is not None
    assert await session.close() is None


def test_the_noop_actions_carry_no_pom_machinery():
    """
    Flow → Action, not Flow → Glue → POM. A domain with no selectors has no POM
    layer to protect, so its actions are ActionStrategy subclasses and have no
    _build_pom to forget a resolver in. See plan §4.
    """
    from stepper.engine.pages.glue_action import GlueAction
    from stepper.sites._noop.pages.noop_page import NoopPage

    assert NoopPage.domain == "noop"
    for action in (NoopPage.NoopSetAction(), NoopPage.NoopEchoAction()):
        assert not isinstance(action, GlueAction)
        assert not hasattr(action, "_build_pom")


# ── The actions, run through a real StepRunner ────────────────────────────────

class _NullReporter:
    def __init__(self):
        self.rows = []

    def record_step(self, result):
        self.rows.append(result)


def _steps_from_workflow() -> list[StepConfig]:
    raw = json.loads(_WORKFLOW.read_text(encoding="utf-8"))
    return [
        StepConfig(action=s["action"], description=s.get("description", ""),
                   extra=s.get("extra", {}), when=s.get("when"))
        for s in raw["steps"]
    ]


async def test_the_shipped_workflow_runs_with_nothing_injected():
    from stepper.engine.actions.factory import build_default_registry
    from stepper.sites._noop.pages.noop_page import NoopPage

    registry = build_default_registry()
    NoopPage.register(registry)
    reporter = _NullReporter()

    session = await NullSession("noop").open()
    runner  = StepRunner(session=session, action_factory=registry,
                         reporter=reporter, hooks=[])

    results, ctx = await runner.run(_steps_from_workflow())

    assert [r.status for r in results] == ["passed", "passed", "skipped"]
    assert ctx.counts == {"widgets": 3}
    assert results[1].output == {"widgets": 3}
    assert len(reporter.rows) == 3
    assert isinstance(runner._resolver, NullResolver)


async def test_noop_set_needs_a_key():
    from stepper.sites._noop.pages.noop_page import NoopPage

    result = await NoopPage.NoopSetAction().execute(
        None, StepConfig(action="noop_set", extra={}), None, ExecutionContext(),
    )

    assert result.status == "failed"
    assert "extra.key" in result.error


async def test_noop_echo_says_when_nothing_is_stored():
    from stepper.sites._noop.pages.noop_page import NoopPage

    result = await NoopPage.NoopEchoAction().execute(
        None, StepConfig(action="noop_echo", extra={"key": "absent"}),
        None, ExecutionContext(),
    )

    assert result.status == "failed"
    assert "absent" in result.error
