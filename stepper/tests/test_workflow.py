"""
test_workflow.py — Runs stepper JSON workflows as pytest tests.

Usage:
    cd stepper
    pytest tests/ -v               # headless
    pytest tests/ -v --headed      # visible browser
    pytest tests/ --junitxml=reports/junit.xml   # CI/CD output
"""
import sys
from pathlib import Path

import pytest

# Ensure stepper/ and repo root are importable regardless of cwd
_stepper_dir = Path(__file__).resolve().parent.parent   # stepper/
_repo_root   = _stepper_dir.parent                       # playwright-stepper-framework/
for _p in (_repo_root, _stepper_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import run  # noqa: E402  (stepper/main.py)

WORKFLOWS_DIR = _stepper_dir / "sites" / "openlibrary" / "workflows"


def _resolve_workflow(name_or_path: str) -> Path:
    """Accept a bare filename (looked up in WORKFLOWS_DIR) or an absolute path."""
    p = Path(name_or_path)
    if p.is_absolute():
        return p
    candidate = WORKFLOWS_DIR / name_or_path
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Workflow not found: {name_or_path!r}\n"
        f"  looked in: {WORKFLOWS_DIR}"
    )


def _check_failures(results):
    failed = [r for r in results if r.status == "failed"]
    assert not failed, "\n".join(
        f"  FAIL step {i+1} {r.step.description!r}: {r.error}"
        for i, r in enumerate(failed)
    )


@pytest.mark.asyncio
async def test_ol_search_and_add(stepper_browser, stepper_resolver):
    """Full search-and-add workflow: search books, add to reading list, verify count."""
    results = await run(
        workflow_path=str(WORKFLOWS_DIR / "ol_search_and_add.json"),
        _browser=stepper_browser,
        resolver=stepper_resolver,
    )
    _check_failures(results)


@pytest.mark.asyncio
async def test_ol_smoke(stepper_browser, stepper_resolver):
    """Smoke test: quick sanity check that the site is reachable and searchable."""
    results = await run(
        workflow_path=str(WORKFLOWS_DIR / "ol_smoke_test.json"),
        _browser=stepper_browser,
        resolver=stepper_resolver,
    )
    _check_failures(results)


@pytest.mark.asyncio
async def test_data_driven(stepper_browser, stepper_resolver, test_case, request):
    """Data-driven workflow test.

    Requires --workflow and --data.  Optionally --case N (default 0) or --all-cases.

    Examples:
        pytest tests/ -v --workflow ol_search_and_add.json --data path/to/data.json
        pytest tests/ -v --workflow ol_search_and_add.json --data path/to/data.json --all-cases
        pytest tests/ -v --workflow ol_search_and_add.json --data path/to/data.json --case 2
    """
    workflow_path = _resolve_workflow(request.config.getoption("--workflow"))
    results = await run(
        workflow_path=str(workflow_path),
        variables=test_case,
        _browser=stepper_browser,
        resolver=stepper_resolver,
    )
    _check_failures(results)
