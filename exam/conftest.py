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
from pathlib import Path

# ── Load .env file before anything else ──────────────────────────────────────
# Looks in project root first, then exam/, then stepper/ as fallback.
def _load_env() -> None:
    _here = Path(__file__).resolve().parent
    for candidate in (_here.parent / ".env", _here / ".env", _here.parent / "stepper" / ".env"):
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

import argparse

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from poms.shared.driver import PlaywrightDriver
from poms.openLibrary.config import load_settings, load_test_data
from poms.openLibrary.pages.login_page import LoginPage


def _has_credentials() -> bool:
    return bool(os.environ.get("OPENLIBRARY_USERNAME") and os.environ.get("OPENLIBRARY_PASSWORD"))


requires_auth = pytest.mark.skipif(
    not _has_credentials() and not load_settings().storage_state_path.exists(),
    reason="No saved session and no OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD set",
)


def pytest_addoption(parser):
    try:
        parser.addoption("--headed", action="store_true", default=False,
                         help="Run browser in headed (visible) mode")
    except (ValueError, argparse.ArgumentError):
        pass  # already registered by stepper/conftest.py or pytest-playwright
    try:
        parser.addoption("--case", type=int, default=0,
                         help="Index of the test case in testdata.json to run (default: 0)")
    except (ValueError, argparse.ArgumentError):
        pass
    try:
        parser.addoption("--all-cases", action="store_true", default=False,
                         help="Run all test cases from testdata.json")
    except (ValueError, argparse.ArgumentError):
        pass
    try:
        parser.addoption(
            "--clear-before-run", action="store_true", default=False,
            help=(
                "Clear the reading list before adding books. "
                "Enables exact == count assertions instead of >=. "
                "Equivalent to the Stepper's ol_clear_reading_list + when: guard."
            ),
        )
    except (ValueError, argparse.ArgumentError):
        pass


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


@pytest.fixture
def result_key(test_case):
    """Stable tuple key for sharing state between ordered test methods."""
    return (test_case["query"], test_case["max_year"], test_case["limit"])


@pytest.fixture
def clear_before_run(request) -> bool:
    """
    True when --clear-before-run is passed on the CLI.

    Acts as the pytest equivalent of a Stepper when: guard:
      - test_add_books clears the shelf when this is True
      - test_assert_reading_list_count uses == (exact) instead of >= (at-least)

    Usage:
        pytest tests/ -v --clear-before-run
    """
    return request.config.getoption("--clear-before-run", default=False)


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
    login_page = LoginPage(driver, settings.base_url, settings.delays, page=page)
    if not await login_page.is_session_live():
        await login_page.open()
        await login_page.fill_username(os.environ["OPENLIBRARY_USERNAME"])
        await login_page.fill_password(os.environ["OPENLIBRARY_PASSWORD"])
        await login_page.submit()
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


@pytest_asyncio.fixture
async def driver(page):
    """Wraps the per-test Playwright page in the IBrowserDriver interface."""
    return PlaywrightDriver(page)
