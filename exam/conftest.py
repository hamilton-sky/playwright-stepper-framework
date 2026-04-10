"""
conftest.py -- Pytest fixtures for the OpenLibrary exam solution.

Provides browser, page, and auth fixtures used by tests/test_openlibrary_exam.py.

Authentication order:
  1. If artifacts/storage_state.json exists -> loads saved cookies (instant).
  2. Else if OPENLIBRARY_USERNAME + OPENLIBRARY_PASSWORD are set -> auto-login,
     then saves the session so subsequent runs are instant.
  3. Else -> auth-dependent tests are skipped with a clear message.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ── Load .env file before anything else ──────────────────────────────────────
# Looks in exam/ first, then falls back to stepper/ (where .env typically lives).
def _load_env() -> None:
    _here = Path(__file__).resolve().parent
    for candidate in (_here / ".env", _here.parent / "stepper" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value
        break  # stop after first found

_load_env()

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

# ── sys.path: make shared_poms and exam/ importable ──────────────────────────
_repo_root = Path(__file__).resolve().parent.parent   # playwright-stepper-framework/
_exam_dir  = Path(__file__).resolve().parent           # exam/
for _p in (_repo_root, _exam_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared_poms.driver import PlaywrightDriver
from shared_poms.config import load_settings, load_test_data
from shared_poms.auth import ensure_logged_in


def _has_credentials() -> bool:
    return bool(os.environ.get("OPENLIBRARY_USERNAME") and os.environ.get("OPENLIBRARY_PASSWORD"))


requires_auth = pytest.mark.skipif(
    not _has_credentials() and not load_settings().storage_state_path.exists(),
    reason="No saved session and no OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD set",
)


def pytest_addoption(parser):
    parser.addoption("--headed", action="store_true", default=False,
                     help="Run browser in headed (visible) mode")
    parser.addoption("--case", type=int, default=0,
                     help="Index of the test case in testdata.json to run (default: 0)")
    parser.addoption("--all-cases", action="store_true", default=False,
                     help="Run all test cases from testdata.json")


def pytest_generate_tests(metafunc):
    if "test_case" not in metafunc.fixturenames:
        return
    cases = load_test_data()
    if metafunc.config.getoption("--all-cases"):
        selected = cases
    else:
        idx = metafunc.config.getoption("--case")
        if idx < 0 or idx >= len(cases):
            raise ValueError(
                f"--case {idx} is out of range: testdata.json has {len(cases)} case(s) (0-{len(cases)-1})"
            )
        selected = [cases[idx]]
    ids = [c.get("comment", c["query"]) for c in selected]
    metafunc.parametrize("test_case", selected, ids=ids)


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def _shared_results():
    """Session-scoped dict for passing state between ordered test methods.

    Keyed by (query, max_year, limit) so that two cases with the same
    query but different filters never collide.
    """
    return {}


@pytest_asyncio.fixture(scope="session")
async def browser(request):
    headless = not request.config.getoption("--headed")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        yield browser
        await browser.close()


@pytest_asyncio.fixture(scope="session")
async def _authed_storage_state(browser, settings):
    """
    Runs once per session. Logs in if needed, saves session, returns path.
    """
    if settings.storage_state_path and settings.storage_state_path.exists():
        return str(settings.storage_state_path)

    if not _has_credentials():
        return None

    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    driver = PlaywrightDriver(page)
    await ensure_logged_in(
        driver,
        os.environ["OPENLIBRARY_USERNAME"],
        os.environ["OPENLIBRARY_PASSWORD"],
        settings.base_url,
    )
    await asyncio.sleep(1)
    await driver.goto(
        f"{settings.base_url}/account/books/want-to-read",
        wait_until="domcontentloaded",
    )
    settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(settings.storage_state_path))
    await context.close()
    return str(settings.storage_state_path)


@pytest_asyncio.fixture
async def page(browser, settings, _authed_storage_state):
    """Fresh browser context + page per test, with login cookies when available."""
    ctx_kwargs = {"viewport": {"width": 1280, "height": 800}}
    if _authed_storage_state:
        ctx_kwargs["storage_state"] = _authed_storage_state
    context = await browser.new_context(**ctx_kwargs)
    page = await context.new_page()
    yield page
    await context.close()
