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

#: The generic names this distribution must never install at the top level.
#: `engine`, `bootstrap` and `sites` were all top-level packages once; any of
#: them would shadow, or be shadowed by, an unrelated package in the same
#: environment.
_FORBIDDEN_TOP_LEVEL = ("engine", "bootstrap", "sites", "main", "cli")


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def find_config(config) -> dict:
    return config["tool"]["setuptools"]["packages"]["find"]


def _top_level_packages() -> set[str]:
    """Directories with an __init__.py at the packaging root."""
    return {init.parent.name for init in _REPO_ROOT.glob("*/__init__.py")}


# ── The roots ─────────────────────────────────────────────────────────────────

def test_there_is_one_source_root(find_config):
    """
    Everything ships from the repo root: `poms` and the `stepper` namespace.

    The second root (`stepper`) is what made `engine`, `bootstrap` and `sites`
    top-level packages in the wheel.
    """
    assert set(find_config["where"]) == {"."}


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


@pytest.mark.parametrize("package", ["poms", "stepper"])
def test_the_packages_the_engine_needs_are_named(package, find_config):
    """A regression guard on the specific two, since dropping one is silent."""
    assert f"{package}*" in find_config["include"]


@pytest.mark.parametrize("name", _FORBIDDEN_TOP_LEVEL)
def test_no_generic_name_is_importable_at_the_top_level(name):
    """
    `pip install .` must not drop `engine/`, `sites/` or `bootstrap/` into
    site-packages. They are `stepper.engine`, `stepper.sites` and
    `stepper.bootstrap`; a directory reappearing at the root would silently put
    them back.
    """
    assert not (_REPO_ROOT / name / "__init__.py").exists(), (
        f"{name}/ is importable at the repo root again — it belongs under stepper/"
    )


@pytest.mark.parametrize("name", _FORBIDDEN_TOP_LEVEL)
def test_nothing_imports_the_old_top_level_names(name):
    """
    The whole point of the namespace move is that no module reaches for the
    bare name any more. One `from engine.x import y` left behind works from a
    checkout (the repo root is on sys.path) and fails on an installed copy.
    """
    offenders = []
    for path in _REPO_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith((f"from {name}.", f"from {name} import",
                                    f"import {name}.", f"import {name}")):
                # `import stepper.engine` starts with neither; only the bare
                # name matches, and `import maintenance` is excluded by the
                # word boundary the f-strings above already imply.
                if stripped in (f"import {name}",) or stripped.startswith(
                        (f"from {name}.", f"from {name} import", f"import {name}.")):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {stripped}")

    assert not offenders, "Imports of the old top-level name:\n  " + "\n  ".join(offenders)


def test_every_directory_of_modules_is_a_package():
    """
    A directory of .py files with no __init__.py is invisible to
    `find_packages`, so it is simply absent from the wheel — silently, because
    a checkout imports it fine via the repo root on sys.path.

    `poms/openLibrary/` was exactly this: an installed copy shipped the
    SauceDemo and phpTravels page objects and not one OpenLibrary page object,
    so every `ol_*` workflow would fail on an import error.
    """
    from setuptools import find_packages

    shipped = set(find_packages(
        where=str(_REPO_ROOT), include=["poms*", "stepper*"], exclude=["stepper.tests*"],
    ))

    missing = []
    for root_name in ("poms", "stepper"):
        root = _REPO_ROOT / root_name
        for directory in sorted(root.rglob("*")):
            if not directory.is_dir():
                continue
            parts = directory.relative_to(_REPO_ROOT).parts
            if any(p in ("__pycache__", "tests", "artifacts", "models") for p in parts):
                continue
            if not any(directory.glob("*.py")):
                continue
            if ".".join(parts) not in shipped:
                missing.append("/".join(parts))

    assert not missing, (
        "These directories hold modules but would not be installed — "
        "each needs an __init__.py:\n  " + "\n  ".join(missing)
    )


# ── Data files ────────────────────────────────────────────────────────────────

def test_workflows_and_config_are_shipped_as_package_data(config):
    """
    Without this, a wheel ships every action and not one workflow to run —
    `run ol_smoke_test` on an installed copy would find nothing.
    """
    patterns = config["tool"]["setuptools"]["package-data"]["*"]

    assert "workflows/*.json" in patterns
    assert "config/*.yaml" in patterns


def test_a_console_script_is_declared(config):
    """`stepper` on the PATH is the point of installing it."""
    assert config["project"]["scripts"]["stepper"] == "stepper.main:main"


def test_every_workflow_directory_is_covered(config):
    patterns = config["tool"]["setuptools"]["package-data"]["*"]
    workflow_dirs = {p.parent for p in (_REPO_ROOT / "stepper" / "sites").glob("*/workflows")}

    assert workflow_dirs, "no workflow directories found; this test would pass vacuously"
    assert any(p.startswith("workflows/") for p in patterns)


# ── Model weights are a cache, not source ────────────────────────────────────

def test_no_model_weights_are_tracked():
    """
    An 87MB all-MiniLM-L6-v2/model.safetensors was committed once, which made
    `git clone` cost 85MB of history for a file `stepper/download_models.py`
    fetches on demand. Both loaders fall back to the hub id when the directory
    is absent, so nothing under stepper/models/ needs to be in the repo.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "stepper/models"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()

    assert not tracked, (
        "Model weights are tracked again:\n  " + "\n  ".join(tracked)
        + "\n\nThey are a download cache. `git rm -r --cached stepper/models`."
    )


def test_both_model_loaders_fall_back_to_the_hub():
    """
    Each loader must name a hub id when no local copy is on disk. Without it,
    an absent stepper/models/ silently degrades the resolver to Jaccard word
    overlap and the healer to no re-ranking — both still "work", much worse,
    and neither says so above DEBUG.
    """
    from stepper.engine.resolvers import strategies as resolver_strategies
    from stepper.engine.healer import dom_snapshot

    assert resolver_strategies._MINILM_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
    assert dom_snapshot._CROSS_ENCODER_MODEL == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ...and the local path is consulted via .exists(), not assumed.
    source = (_REPO_ROOT / "stepper/engine/resolvers/strategies.py").read_text(encoding="utf-8")
    assert "_MINILM_LOCAL.exists()" in source


# ── The path bootstrap ────────────────────────────────────────────────────────

def test_main_does_not_reference_a_directory_that_does_not_exist():
    """The path bootstrap used to add stepper/src/, which has never existed."""
    assert not (_REPO_ROOT / "stepper" / "src").exists()

    source = (_REPO_ROOT / "stepper" / "main.py").read_text(encoding="utf-8")
    assert '"src"' not in source
