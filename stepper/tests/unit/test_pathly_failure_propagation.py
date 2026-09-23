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

Three rules here, all guarding the same property — a Pathly step may not claim
something it did not establish:

  1. static     — no POM method discards _interact's result
  2. behavioural — no glue action returns "passed" when it is False
  3. reporting  — the two actions whose job is to report a fact
                  (pathly_assert_projects, pathly_read_routing) must not pass
                  vacuously or drop the value they read

All three fail against the code they were written for.
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


# ── The reporting actions: no vacuous pass, no value thrown away ──────────────
#
# The same rule from the other side. pathly_assert_projects and
# pathly_read_routing do not drive an element, so the guards above do not cover
# them — but they are the two steps whose whole job is to report a fact, which
# is where a false green costs the most.

def _home_screen_listing(names: list[str], monkeypatch):
    """Pin what the home screen appears to list, with no browser."""
    from poms.pathly.pages.home_screen_page import HomeScreenPage

    async def _fake(self):
        return names
    monkeypatch.setattr(HomeScreenPage, "get_project_names", _fake)


def _assert_projects(extra):
    from stepper.sites.pathly.pages.home_screen_action import PathlyHomeScreen
    return _run(PathlyHomeScreen.PathlyAssertProjectsAction(), extra)


@pytest.mark.parametrize("extra", [
    pytest.param({}, id="key-absent"),
    pytest.param({"expected_name": ["Alpha"]}, id="key-misspelled"),
    pytest.param({"expected_names": []}, id="empty-list"),
    pytest.param({"expected_names": None}, id="null"),
    pytest.param({"expected_names": "Alpha"}, id="bare-string"),
    pytest.param({"expected_names": [1, 2]}, id="not-strings"),
])
def test_assert_projects_refuses_to_assert_nothing(extra, monkeypatch):
    """
    `extra.get("expected_names", [])` made `missing` empty, so the step passed
    whatever the app showed. A misspelled key is the realistic way in, and it
    is invisible: the run is green.

    The bare-string case is its own trap — `n not in actual` would have
    iterated the characters of "Alpha".
    """
    _home_screen_listing(["something", "else"], monkeypatch)

    result = _assert_projects(extra)

    assert result.status == "failed", (
        f"{extra!r} produced {result.status!r}; an assertion with nothing to "
        f"assert must not report success"
    )
    assert "expected_names" in (result.error or "")


def test_assert_projects_still_passes_when_the_projects_are_there(monkeypatch):
    _home_screen_listing(["Alpha", "Beta"], monkeypatch)

    result = _assert_projects({"expected_names": ["Alpha"]})

    assert result.status == "passed"
    assert result.output == {"pathly_projects": ["Alpha", "Beta"]}


def test_assert_projects_fails_and_names_both_sides_when_one_is_missing(monkeypatch):
    _home_screen_listing(["Alpha"], monkeypatch)

    result = _assert_projects({"expected_names": ["Alpha", "Gamma"]})

    assert result.status == "failed"
    assert "Gamma" in result.error, "the error should name what was expected"
    assert "Alpha" in result.error, "and what was actually on screen"


def _read_routing(extra, monkeypatch, engine="llm"):
    from poms.pathly.pages.settings_page import SettingsPage
    from stepper.sites.pathly.pages.settings_action import PathlySettings

    async def _fake(self):
        return engine
    monkeypatch.setattr(SettingsPage, "get_routing_engine", _fake)

    action = PathlySettings.PathlyReadRoutingAction()
    step = StepConfig(action=action.action_name, description="probe", extra=extra)
    ctx = ExecutionContext()
    result = asyncio.run(action.execute(MagicMock(), step, MagicMock(), ctx, None))
    return result, ctx


def test_read_routing_puts_the_value_in_the_context(monkeypatch):
    """
    Its docstring says "into the context". It logged the value and dropped it,
    so no later `when:` clause and nothing in results.json could see it — the
    action could not deliver the one thing it exists to produce.
    """
    result, ctx = _read_routing({}, monkeypatch, engine="python-fsm")

    assert result.status == "passed"
    assert ctx.get("pathly_routing_engine") == "python-fsm"
    assert result.output == {"pathly_routing_engine": "python-fsm"}


def test_read_routing_honours_an_explicit_key(monkeypatch):
    """Same shape as StoreAction's extra.key, so workflows read the same way."""
    result, ctx = _read_routing({"key": "engine_before"}, monkeypatch, engine="llm")

    assert ctx.get("engine_before") == "llm"
    assert result.output == {"engine_before": "llm"}


def test_a_later_step_can_read_what_read_routing_stored(monkeypatch):
    """
    The end the fix exists for: `context.store` writes the generic map, which
    is what `context_lookup` reads, so a following step's `{{...}}` resolves.
    Storing under a key nothing can reach would satisfy the test above and
    still be useless.
    """
    from stepper.engine.runner.interpolation import context_lookup, resolve

    _, ctx = _read_routing({}, monkeypatch, engine="python-fsm")

    resolved, missing = resolve({"engine": "{{pathly_routing_engine}}"},
                                context_lookup(ctx))

    assert missing == []
    assert resolved == {"engine": "python-fsm"}
