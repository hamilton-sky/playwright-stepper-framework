"""
Regression tests for the ActionStrategy template method.

Guards the contract that used to be broken in two ways:

  1. ActionStrategy.execute() called _execute() with four arguments while the
     abstract signature declared five, so `behaviour` never reached engine
     actions at all.
  2. GlueAction worked around that by overriding execute() — the one method the
     base class documents as "do NOT override" — which meant every glue action
     silently skipped pre_execute/post_execute and ExecutionContext defaulting.

There is now exactly one execution path. These tests fail if anyone
reintroduces a second one.
"""
from __future__ import annotations

import pytest

from stepper.engine.interfaces import ActionStrategy, ExecutionContext, StepConfig, StepResult
from stepper.engine.pages.glue_action import GlueAction


class _Recorder:
    """Shared spy mixin — records hook order and what _execute received."""

    def __init__(self):
        self.calls: list[str] = []
        self.seen_behaviour = "NOT-CALLED"
        self.seen_context = "NOT-CALLED"

    async def pre_execute(self, page, step):
        self.calls.append("pre")

    async def post_execute(self, page, step, result):
        self.calls.append("post")


class EngineAction(_Recorder, ActionStrategy):
    action_name = "spy_engine"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls.append("execute")
        self.seen_behaviour = behaviour
        self.seen_context = context
        return StepResult(step=step, status="passed")


class SiteGlueAction(_Recorder, GlueAction):
    action_name = "spy_glue"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls.append("execute")
        self.seen_behaviour = behaviour
        self.seen_context = context
        return StepResult(step=step, status="passed")


@pytest.fixture
def step():
    return StepConfig(action="spy", description="spy step")


ACTIONS = [EngineAction, SiteGlueAction]


@pytest.mark.parametrize("action_cls", ACTIONS)
async def test_hooks_fire_around_execute(action_cls, step):
    """pre_execute and post_execute must wrap _execute for engine AND glue."""
    action = action_cls()
    await action.execute(None, step, None, ExecutionContext(), None)
    assert action.calls == ["pre", "execute", "post"]


@pytest.mark.parametrize("action_cls", ACTIONS)
async def test_behaviour_is_forwarded(action_cls, step):
    """The behaviour instance the runner passes must reach _execute."""
    behaviour = object()
    action = action_cls()
    await action.execute(None, step, None, ExecutionContext(), behaviour)
    assert action.seen_behaviour is behaviour


@pytest.mark.parametrize("action_cls", ACTIONS)
async def test_missing_behaviour_defaults_to_none(action_cls, step):
    """Callers that omit behaviour (nested dispatch, tests) still work."""
    action = action_cls()
    await action.execute(None, step, None, ExecutionContext())
    assert action.seen_behaviour is None


@pytest.mark.parametrize("action_cls", ACTIONS)
async def test_none_context_is_defaulted(action_cls, step):
    """context=None must become a real ExecutionContext before _execute sees it."""
    action = action_cls()
    await action.execute(None, step, None, None, None)
    assert isinstance(action.seen_context, ExecutionContext)


@pytest.mark.parametrize("action_cls", ACTIONS)
def test_execute_is_not_overridden(action_cls):
    """
    execute() is the template method. Only ActionStrategy may define it —
    an override is what broke the hooks last time.
    """
    assert action_cls.execute is ActionStrategy.execute


def test_glue_action_does_not_define_execute():
    assert "execute" not in vars(GlueAction)


# ── The strategies.py split ───────────────────────────────────────────────────

def test_strategies_is_a_shim_and_stays_one():
    """
    strategies.py was one 1331-line file holding 23 action classes. It is now a
    re-export surface over basic / assertions / data / flow / measurement, kept
    so existing imports still resolve.

    A class defined here again means the split is being undone one action at a
    time — which is exactly how it got to 1331 lines the first time.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "engine" / "actions" / "strategies.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    defined = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert not defined, (
        "strategies.py defines classes again: " + ", ".join(defined)
        + "\nPut them in the module they belong to and re-export here."
    )


def test_every_action_module_stays_readable():
    """
    A soft ceiling, deliberately generous. It is not about the number; it is
    that nothing silently grows back into a thousand-line bag of classes.
    """
    from pathlib import Path

    actions_dir = Path(__file__).resolve().parents[2] / "engine" / "actions"
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in sorted(actions_dir.glob("*.py"))
        if len(path.read_text(encoding="utf-8").splitlines()) > 600
    }

    assert not oversized, (
        "These action modules are over 600 lines: "
        + ", ".join(f"{n} ({c})" for n, c in oversized.items())
        + "\nSplit by what the actions do, as basic/assertions/data/flow/measurement are."
    )


def test_the_shim_exports_every_registered_action():
    """
    Anything build_default_registry() constructs must still be importable from
    strategies.py — that is the whole contract the shim exists to keep.
    """
    from stepper.engine.actions import strategies
    from stepper.engine.actions.factory import build_default_registry

    registered = {type(action).__name__ for _, action in build_default_registry().items()}
    exported = set(strategies.__all__)

    assert registered <= exported, (
        "Registered but not re-exported: " + ", ".join(sorted(registered - exported))
    )
