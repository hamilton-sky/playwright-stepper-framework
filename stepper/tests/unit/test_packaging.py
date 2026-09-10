"""
Every importable top-level package is one the distribution actually ships.

`pyproject.toml` listed only `poms*`, so `pip install .` produced a wheel with
the page objects and none of the engine that drives them — a distribution that
imports and cannot run anything. Nothing caught it because nothing installs the
package during development; the suite runs from a checkout, where sys.path
covers the gap.

These tests read the packaging config rather than the built wheel, so they are
fast and need no build. They fail when a new top-level package or data
directory is added without being declared.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: Directories that hold importable code but are not shipped, with the reason.
_NOT_SHIPPED = {
    "examples": "reference material for readers, not a runtime dependency",
    "tests": "the suite itself",
}


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def find_config(config) -> dict:
    return config["tool"]["setuptools"]["packages"]["find"]


def _top_level_packages() -> set[str]:
    """Directories with an __init__.py under either packaging root."""
    found = set()
    for root in (_REPO_ROOT, _REPO_ROOT / "stepper"):
        for init in root.glob("*/__init__.py"):
            found.add(init.parent.name)
    return found


# ── The roots ─────────────────────────────────────────────────────────────────

def test_both_source_roots_are_declared(find_config):
    """poms lives at the repo root; the engine packages live under stepper/."""
    assert set(find_config["where"]) == {".", "stepper"}


def test_the_discovery_finds_something(find_config):
    assert _top_level_packages(), "package discovery is broken; the rest would pass vacuously"


# ── Every package is shipped ──────────────────────────────────────────────────

def test_every_top_level_package_is_included(find_config):
    patterns = {p.rstrip("*") for p in find_config["include"]}
    missing = sorted(
        name for name in _top_level_packages()
        if name not in _NOT_SHIPPED and name not in patterns
    )

    assert not missing, (
        "These packages are importable but would not be installed:\n  "
        + "\n  ".join(missing)
        + f"\n\nAdd them to [tool.setuptools.packages.find] include in {_PYPROJECT.name}, "
        "or to _NOT_SHIPPED here with a reason."
    )


@pytest.mark.parametrize("package", ["poms", "engine", "bootstrap", "sites"])
def test_the_packages_the_engine_needs_are_named(package, find_config):
    """A regression guard on the specific four, since dropping one is silent."""
    assert f"{package}*" in find_config["include"]


# ── Data files ────────────────────────────────────────────────────────────────

def test_workflows_and_config_are_shipped_as_package_data(config):
    """
    Without this, a wheel ships every action and not one workflow to run —
    `run ol_smoke_test` on an installed copy would find nothing.
    """
    patterns = config["tool"]["setuptools"]["package-data"]["*"]

    assert "workflows/*.json" in patterns
    assert "config/*.yaml" in patterns


def test_every_workflow_directory_is_covered(config):
    patterns = config["tool"]["setuptools"]["package-data"]["*"]
    workflow_dirs = {p.parent for p in (_REPO_ROOT / "stepper" / "sites").glob("*/workflows")}

    assert workflow_dirs, "no workflow directories found; this test would pass vacuously"
    assert any(p.startswith("workflows/") for p in patterns)


# ── The path bootstrap ────────────────────────────────────────────────────────

def test_main_does_not_reference_a_directory_that_does_not_exist():
    """The path bootstrap used to add stepper/src/, which has never existed."""
    assert not (_REPO_ROOT / "stepper" / "src").exists()

    source = (_REPO_ROOT / "stepper" / "main.py").read_text(encoding="utf-8")
    assert '"src"' not in source
