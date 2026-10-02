"""
The three-layer contract, enforced by the build rather than by an audit.

    Flow (workflow JSON) → Glue (stepper/sites/*/pages) → POM (poms/)

Until this file existed the direction was checked only by `/verify-layers`, an
audit someone has to remember to run. Every other rule in the contract that can
be read off the source is here, so a violation fails CI on the push that adds it.

What is deliberately *not* here: a workflow handing an element cfg to an
engine-level action (`click`, `assert_visible`, …). That is a supported feature —
the heal-test flows exist to feed the cascade broken selectors — so the flow rule
below applies to site actions only, whose selectors belong in their POM.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
POMS = ROOT / "poms"
SITES = ROOT / "stepper" / "sites"

_PAGE_QUERY_METHODS = {"locator", "query_selector", "query_selector_all", "wait_for_selector"}
_SELECTOR_KEYS = {"css", "xpath", "selector", "selectors"}


def _py_files(base: Path):
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# ── POM → never imports the engine ───────────────────────────────────────────

def _stepper_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "stepper"]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] == "stepper":
                found.append(node.module)
    return found


def test_there_are_pom_files_to_check():
    assert len(_py_files(POMS)) > 10


@pytest.mark.parametrize("path", _py_files(POMS), ids=_rel)
def test_no_pom_imports_from_stepper(path):
    bad = _stepper_imports(path)
    assert not bad, (
        f"{_rel(path)} imports {bad}. POMs sit below the engine: "
        "Flow → Glue → POM, never reversed."
    )


# ── Glue → never queries the page with raw selectors ─────────────────────────

def _glue_files():
    return [p for p in _py_files(SITES) if p.parent.name == "pages"]


def _raw_page_queries(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name in _PAGE_QUERY_METHODS or name.startswith("get_by_"):
            hits.append(f"line {node.lineno}: .{name}(…)")
    return hits


def test_there_are_glue_files_to_check():
    assert len(_glue_files()) > 10


@pytest.mark.parametrize("path", _glue_files(), ids=_rel)
def test_glue_never_queries_the_page_directly(path):
    hits = _raw_page_queries(path)
    assert not hits, (
        f"{_rel(path)} queries the page itself: {hits}. That bypasses the "
        "resolver cascade — give the element a Locator on the POM and call the POM."
    )


# ── Flow → no selectors on site actions ──────────────────────────────────────

def _workflows():
    return sorted(SITES.glob("*/workflows/*.json"))


def _site_prefixes() -> set[str]:
    prefixes = set()
    for site_dir in SITES.iterdir():
        for glue in site_dir.glob("pages/*.py"):
            for node in ast.walk(ast.parse(glue.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "site" for t in node.targets)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    prefixes.add(node.value.value + "_")
    return prefixes


def _steps(obj):
    """Every dict carrying an "action", however deeply nested."""
    if isinstance(obj, dict):
        if "action" in obj:
            yield obj
        for v in obj.values():
            yield from _steps(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _steps(v)


def _selector_keys(obj) -> set[str]:
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SELECTOR_KEYS:
                keys.add(k)
            if k not in ("steps", "login_steps"):
                keys |= _selector_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _selector_keys(v)
    return keys


def test_there_are_workflows_and_site_prefixes_to_check():
    assert len(_workflows()) >= 20
    assert {"ol_", "sd_", "pt_", "ti_"} <= _site_prefixes()


@pytest.mark.parametrize("path", _workflows(), ids=_rel)
def test_site_actions_in_a_workflow_carry_no_selectors(path):
    prefixes = tuple(_site_prefixes())
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = []
    for step in _steps(data):
        action = str(step.get("action", ""))
        if not action.startswith(prefixes):
            continue
        body = {k: v for k, v in step.items() if k != "action"}
        keys = _selector_keys(body)
        if keys:
            bad.append(f"{action}: {sorted(keys)}")
    assert not bad, (
        f"{_rel(path)} passes selectors to site actions: {bad}. "
        "A site action's selectors belong in its POM, not in the flow."
    )
