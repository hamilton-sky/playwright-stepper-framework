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


@pytest.mark.asyncio
async def test_ol_search_and_add(request):
    """Full search-and-add workflow: search books, add to reading list, verify count."""
    headless = not request.config.getoption("--headed")
    results = await run(
        workflow_path=str(WORKFLOWS_DIR / "ol_search_and_add.json"),
        headless=headless,
    )
    failed = [r for r in results if r.status == "failed"]
    assert not failed, "\n".join(
        f"  FAIL step {i+1} {r.step.description!r}: {r.error}"
        for i, r in enumerate(failed)
    )


@pytest.mark.asyncio
async def test_ol_smoke(request):
    """Smoke test: quick sanity check that the site is reachable and searchable."""
    headless = not request.config.getoption("--headed")
    results = await run(
        workflow_path=str(WORKFLOWS_DIR / "ol_smoke_test.json"),
        headless=headless,
    )
    failed = [r for r in results if r.status == "failed"]
    assert not failed, "\n".join(
        f"  FAIL step {i+1} {r.step.description!r}: {r.error}"
        for i, r in enumerate(failed)
    )
