"""
A step that did not act must not report "passed". Repo-wide.

`SharedBasePage._interact` never raises. A missing selector, a resolver
confidence below CONFIDENCE_WARN, and a click that does not land all come back
the same way: False. Every site in this tree once dropped that value on the
floor, and the glue then returned status="passed" unconditionally.

That is not a hypothetical. It shipped three times:

  pathly    pathly_wizard_smoke — nine interactions and a screenshot, no
            assertion anywhere — reported ten passed steps against an app
            whose wizard never opened.
  ti        HoversPage used `.figure:nth-child(1) img`, which matches nothing
            (the-internet puts an <h3> and a <br> ahead of the figures, so
            they are children 3, 4 and 5). The hover never fired, the
            CSS-hidden link was never clickable, and the flow reported 1/1.
  db        a workflow reported 8/8 while writing "{{item}}" literally,
            because the assertion compared it against the same unresolved
            literal and agreed with itself.

Each was found by *running* the thing, and each was invisible until then —
`validate` said 30/30 throughout. The rules below are what stops the next
generated site from shipping the same shape: they are static, so they hold for
the sites this environment cannot reach (saucedemo, openlibrary and phptravels
are all denied by its egress policy) and for ones nobody has run yet.

Behaviour is covered per site, in test_ti_failure_propagation.py and
test_pathly_failure_propagation.py. This file is only the two static rules.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POMS = _REPO_ROOT / "poms"
_SITES = _REPO_ROOT / "stepper" / "sites"

#: SharedBasePage is where _interact lives; it is the one that may use it freely.
_EXEMPT = {(_POMS / "shared" / "base_page.py").resolve()}


def _rel(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


def _pom_files() -> list[Path]:
    return sorted(p for p in _POMS.rglob("*.py")
                  if p.name != "__init__.py" and p.resolve() not in _EXEMPT)


def _glue_files() -> list[Path]:
    return sorted(p for p in _SITES.rglob("pages/*.py") if p.name != "__init__.py")


def _dropped_calls(path: Path, names: set[str]) -> list[str]:
    """
    `await thing.method(...)` as a bare statement, where method returns a flag.

    An Expr is a discarded value. Assigning it — `landed = await …`, or even
    `_ = await …` when ignoring it is genuinely deliberate — is not flagged,
    which is the intended way out.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{_rel(path)}:{node.lineno}  {ast.unparse(node.value.value)[:70]}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Attribute)
        and node.value.value.func.attr in names
    ]


def _bool_returning_pom_methods() -> set[str]:
    """Every POM method that answers "did this actually happen?"."""
    names: set[str] = set()
    for path in _pom_files():
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(fn, ast.AsyncFunctionDef) and fn.returns is not None
                    and getattr(fn.returns, "id", "") == "bool"):
                names.add(fn.name)
    return names


# ── Rule 1: the POM must pass the flag up ─────────────────────────────────────

def test_pom_discovery_did_not_break():
    assert len(_pom_files()) > 25, "POM discovery broke; the rule below would pass vacuously"


def test_no_pom_discards_an_interact_result():
    offenders = [hit for path in _pom_files() for hit in _dropped_calls(path, {"_interact"})]

    assert not offenders, (
        "_interact returns False rather than raising when the element is not "
        "there. A POM that discards it reports success for something that never "
        "happened, and the glue above it has nothing to go on.\n"
        "Return it — `return await self._interact(...)` — and let the glue "
        "decide.\n  " + "\n  ".join(offenders)
    )


# ── Rule 2: the glue must act on it ───────────────────────────────────────────

def test_bool_returning_pom_method_discovery_did_not_break():
    names = _bool_returning_pom_methods()
    assert len(names) > 20, (
        f"only {len(names)} bool-returning POM methods found; rule 2 would "
        f"barely check anything"
    )


def test_no_glue_action_drops_a_pom_result():
    names = _bool_returning_pom_methods()
    offenders = [hit for path in _glue_files() for hit in _dropped_calls(path, names)]

    assert not offenders, (
        "These glue actions call a POM method that reports whether it acted, "
        "and ignore the answer — so the step returns \"passed\" whether or not "
        "anything happened.\n"
        "Check it and return a failed StepResult naming what missed. If "
        "ignoring it really is deliberate, assign it (`_ = await ...`) so the "
        "choice is visible.\n  " + "\n  ".join(offenders)
    )
