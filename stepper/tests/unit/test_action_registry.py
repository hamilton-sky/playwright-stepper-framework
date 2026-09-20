"""
ActionRegistry — the name -> action map every workflow resolves through.

Action names share one flat namespace across every site, so a collision is not
a loud failure: the second registration simply overwrites the first, and the
only symptom is a workflow running a different site's action than the one it
names. alias() has guarded against exactly that since it was written;
register() did not. See docs/universal-runner-plan.md, leak L6, ticket T5.
"""
from __future__ import annotations

import pytest

from stepper.engine.actions.factory import ActionRegistry, build_default_registry
from stepper.engine.interfaces import ActionStrategy, StepResult


def _action(name: str):
    class _A(ActionStrategy):
        action_name = name

        async def _execute(self, page, step, resolver, context, behaviour=None):
            return StepResult(step=step, status="passed")

    return _A()


# ── The collision guard ───────────────────────────────────────────────────────

def test_two_different_actions_cannot_share_a_name():
    registry = ActionRegistry().register(_action("click"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_action("click"))


def test_the_collision_error_names_the_action_already_there():
    registry = ActionRegistry()
    first = _action("click")
    registry.register(first)

    with pytest.raises(ValueError, match=type(first).__name__):
        registry.register(_action("click"))


def test_the_first_registration_survives_a_rejected_collision():
    """A refused registration must not have half-replaced the original."""
    registry = ActionRegistry()
    first = _action("click")
    registry.register(first)

    with pytest.raises(ValueError):
        registry.register(_action("click"))

    assert registry.create("click") is first


def test_re_registering_the_same_instance_is_idempotent():
    """
    A registry is rebuilt more than once in a process — `main.py actions`
    builds two — so replaying the identical action must not be an error.
    """
    registry = ActionRegistry()
    action = _action("click")

    registry.register(action).register(action)

    assert registry.create("click") is action
    assert len(registry) == 1


def test_register_is_still_fluent():
    registry = ActionRegistry().register(_action("a")).register(_action("b"))

    assert sorted(registry.names()) == ["a", "b"]


# ── The guard does not fight aliases ──────────────────────────────────────────

def test_an_alias_still_binds_to_the_same_instance():
    registry = ActionRegistry()
    action = _action("collect_items")
    registry.register(action)

    registry.alias("ol_collect_books", "collect_items")

    assert registry.create("ol_collect_books") is action


def test_registering_over_an_alias_is_a_collision():
    """
    The case that motivated the guard: an alias reserves a name, and a later
    site claiming it would silently steal the alias out from under the
    workflows using it.
    """
    registry = ActionRegistry()
    registry.register(_action("collect_items"))
    registry.alias("ol_collect_books", "collect_items")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_action("ol_collect_books"))


# ── The real registry is clean ────────────────────────────────────────────────

def test_the_shipped_registry_builds_without_a_collision():
    """
    If two sites had been quietly overwriting each other, turning the guard on
    would surface it here — a find, not a regression.
    """
    from pathlib import Path

    from stepper.bootstrap.infra import register_all_sites

    registry = build_default_registry()
    register_all_sites(registry, Path(__file__).resolve().parents[2])

    assert len(registry) > 40
