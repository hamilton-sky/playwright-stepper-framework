"""
Every action declares which domain's session it acts on (ticket M1).

StepRunner routes by this attribute, so an action that declares the wrong one
is handed the wrong session — and one that declares nothing is handed None.
These check the declarations are complete and honest, because nothing else
will notice until a mixed-domain workflow does the wrong thing quietly.

See docs/mixed-domain-plan.md §4.1.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from stepper.bootstrap.infra import register_all_sites
from stepper.engine.actions.factory import build_default_registry
from stepper.engine.interfaces import ActionStrategy, StepConfig, StepResult
from stepper.engine.pages.base_page_module import PageModule

_STEPPER = Path(__file__).resolve().parents[2]

#: The only actions that may declare no domain. Both were checked by reading
#: their _execute: neither references its first argument at all.
_SESSION_AGNOSTIC = {"load_test_data", "run_workflow"}


@pytest.fixture(scope="module")
def registry():
    r = build_default_registry()
    register_all_sites(r, _STEPPER)
    return r


# ── The declarations are complete ─────────────────────────────────────────────

def test_every_registered_action_declares_a_domain(registry):
    """
    None is a declaration too — but only these two may make it. Anything else
    silently opting out would be handed no session and fail at first use.
    """
    agnostic = {name for name, a in registry.items() if a.domain is None}

    assert agnostic <= _SESSION_AGNOSTIC, (
        f"these actions declare no domain and are not on the list: "
        f"{sorted(agnostic - _SESSION_AGNOSTIC)}"
    )


def test_the_documented_agnostic_actions_really_ignore_their_session():
    """
    The exemption is only as good as the reading behind it. An action that
    declares no domain gets None, so if it ever touches that argument it breaks
    — catch it here rather than at runtime.
    """
    from stepper.engine.actions.data import LoadTestDataAction
    from stepper.engine.actions.flow import RunWorkflowAction

    for cls in (LoadTestDataAction, RunWorkflowAction):
        src = inspect.getsource(cls._execute)
        first = list(inspect.signature(cls._execute).parameters)[1]
        body = src.split("\n", 1)[1]
        assert first not in body.replace(f"{first}:", ""), (
            f"{cls.__name__} declares domain=None but its _execute mentions "
            f"{first!r}; either it needs a domain or the mention is a bug"
        )


def test_wait_is_a_web_action_despite_appearances():
    """
    The trap this ticket walked into. `wait` looks session-free — one branch is
    a bare asyncio.sleep — but the other calls _wait_for(page, target) for a
    selector or URL fragment. Declaring it agnostic would hand it None and
    break every `{"action": "wait", "wait_for": "..."}` step in the tree.
    """
    from stepper.engine.actions.basic import WaitAction

    assert WaitAction.domain == "web"


def test_the_browser_actions_are_all_web(registry):
    for name in ("navigate", "click", "fill", "assert_text", "screenshot",
                 "measure_performance", "for_each_item", "parallel"):
        assert registry.create(name).domain == "web", name


# ── Glue actions are stamped, not hand-declared ───────────────────────────────

def test_site_actions_take_the_domain_from_their_page_module(registry):
    """
    register_actions() stamps it, so a site action never repeats what its
    PageModule already says — and cannot drift from it.
    """
    for name in ("sd_login", "ol_ensure_login", "pt_login"):
        assert registry.create(name).domain == "web", name


def test_a_non_web_page_module_stamps_its_own_domain(registry):
    for name in ("noop_set", "noop_echo"):
        assert registry.create(name).domain == "noop", name


def test_stamping_happens_at_registration_not_by_hand():
    """The class itself carries no domain; the stamp puts it there."""
    from stepper.sites._noop.pages.noop_page import NoopPage

    fresh = NoopPage.NoopSetAction()
    assert fresh.domain is None          # unstamped instance

    registry = build_default_registry()
    NoopPage.register(registry)

    assert registry.create("noop_set").domain == "noop"


def test_a_page_module_defaults_to_web():
    class _Site(PageModule):
        site = "xx"

        @classmethod
        def register(cls, registry) -> None: ...

    assert _Site.domain == "web"


# ── The contract on ActionStrategy ────────────────────────────────────────────

def test_action_strategy_defaults_to_no_domain():
    """
    So a new engine action that forgets to declare one fails loudly at first
    use rather than inheriting the browser by accident.
    """
    assert ActionStrategy.domain is None


def test_step_result_carries_the_domain_it_ran_against():
    result = StepResult(step=StepConfig(action="x"), status="passed")

    assert result.domain is None
    assert StepResult(step=StepConfig(action="x"), status="passed",
                      domain="db").domain == "db"
