"""
A Pathly action that did not act must not report "passed".

`SharedBasePage._interact` never raises. A missing selector, a resolver
confidence below CONFIDENCE_WARN, and a click that does not land all come back
the same way: False. The Pathly POMs used to drop that value on the floor and
the glue returned status="passed" unconditionally, so `pathly_wizard_smoke` —
open wizard → pick template → name it → next x4 → save → screenshot, with no
assertion anywhere — reported ten passed steps against an app whose wizard had
never opened. The screenshot at the end was of the wrong screen and the run
still said green.

This is the same failure the db domain hit from the other direction: a step
that compares an unresolved value against itself, agrees, and passes. A report
nobody can trust is worse than a red one.

Two rules here. The static one stops a POM method from discarding the flag
again; the behavioural one stops the glue from ignoring it.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stepper.engine.interfaces import ExecutionContext, StepConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PATHLY_POMS = _REPO_ROOT / "poms" / "pathly" / "pages"


# ── The static rule: no POM method throws the flag away ───────────────────────

def _discarded_interacts(path: Path) -> list[str]:
    """`await self._interact(...)` used as a bare statement, its result unread."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Await):
            continue
        call = node.value.value
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_interact"):
            found.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    return found


def _pathly_pom_files() -> list[Path]:
    return sorted(p for p in _PATHLY_POMS.glob("*.py") if p.name != "__init__.py")


def test_pathly_pom_discovery_did_not_break():
    assert len(_pathly_pom_files()) == 4, "the rule below would pass vacuously"


def test_no_pathly_pom_discards_an_interact_result():
    offenders = [hit for path in _pathly_pom_files() for hit in _discarded_interacts(path)]

    assert not offenders, (
        "_interact returns False rather than raising when the element is not "
        "there. Discarding it means the POM reports success for something that "
        "never happened.\nReturn it — `return await self._interact(...)` — and "
        "let the glue decide.\n  " + "\n  ".join(offenders)
    )


# ── The behavioural rule: the glue turns False into a failed step ─────────────

def _actions():
    """Every Pathly action that drives an element, with the extra it needs."""
    from stepper.sites.pathly.pages.home_screen_action import PathlyHomeScreen
    from stepper.sites.pathly.pages.settings_action import PathlySettings
    from stepper.sites.pathly.pages.top_bar_action import PathlyTopBar
    from stepper.sites.pathly.pages.wizard_action import PathlyWizard

    return [
        (PathlyWizard.PathlyOpenWizardAction(), {}),
        (PathlyWizard.PathlyWizardSelectTemplateAction(), {"template_id": "standard-pipeline"}),
        (PathlyWizard.PathlyWizardSetNameAction(), {"name": "test-flow"}),
        (PathlyWizard.PathlyWizardNextAction(), {}),
        (PathlyWizard.PathlyWizardSaveAction(), {}),
        (PathlyTopBar.PathlyNavigatePanelAction(), {"panel": "flow"}),
        (PathlyTopBar.PathlyToggleChatAction(), {}),
        (PathlySettings.PathlySetRoutingAction(), {"engine": "llm"}),
        (PathlySettings.PathlySaveSettingsAction(), {}),
        (PathlyHomeScreen.PathlyNewProjectAction(), {}),
    ]


def _ids():
    return [action.action_name for action, _ in _actions()]


@pytest.fixture
def interact_returns(monkeypatch):
    """Pin _interact's answer without a browser, a page or a resolver."""
    from poms.shared.base_page import BasePage

    def _pin(value: bool):
        async def _fake(self, locator, action, **kwargs):
            return value
        monkeypatch.setattr(BasePage, "_interact", _fake)

    return _pin


def _run(action, extra):
    step = StepConfig(action=action.action_name, description="probe", extra=extra)
    return asyncio.run(action.execute(MagicMock(), step, MagicMock(),
                                      ExecutionContext(), None))


@pytest.mark.parametrize("action, extra", _actions(), ids=_ids())
def test_a_missed_interaction_fails_the_step(action, extra, interact_returns):
    interact_returns(False)

    result = _run(action, extra)

    assert result.status == "failed", (
        f"{action.action_name} reported {result.status!r} for an element that "
        f"was never found. A smoke test built from these would go green against "
        f"an app that did nothing."
    )
    assert action.action_name in (result.error or ""), (
        "the error should name the action that missed, so a run log points at "
        "the step rather than at the framework"
    )


@pytest.mark.parametrize("action, extra", _actions(), ids=_ids())
def test_a_landed_interaction_still_passes(action, extra, interact_returns):
    """The other half — the guard must not fail a step that worked."""
    interact_returns(True)

    assert _run(action, extra).status == "passed"
