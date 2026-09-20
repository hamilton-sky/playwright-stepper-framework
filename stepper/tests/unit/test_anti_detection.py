"""
AntiDetection — the browser-level defences applied while building a session.

Every method here degrades when an optional dependency is missing, which is the
whole risk: a degraded run looks identical to a working one. `patchright`,
`playwright-stealth` and a proxy are all absent on a default install, so the
paths that matter most in production are the ones nobody exercises locally.

These tests use page doubles. No browser is launched.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.browser.anti_detection import _DEFAULT_UA, AntiDetection


@pytest.fixture(autouse=True)
def no_proxy_env(monkeypatch):
    """These vars leak in from a developer's shell and change what is asserted."""
    for var in ("BROWSER_USER_AGENT", "PROXY_SERVER", "PROXY_USERNAME", "PROXY_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


# ── context_kwargs ────────────────────────────────────────────────────────────

def test_a_user_agent_is_always_set():
    """
    Playwright's default UA contains "HeadlessChrome", which is the single
    loudest automation signal there is. Something must always override it.
    """
    kwargs = AntiDetection.context_kwargs()

    assert kwargs["user_agent"] == _DEFAULT_UA
    assert "Headless" not in kwargs["user_agent"]


def test_the_user_agent_can_be_overridden_from_the_environment(monkeypatch):
    monkeypatch.setenv("BROWSER_USER_AGENT", "MyAgent/1.0")

    assert AntiDetection.context_kwargs()["user_agent"] == "MyAgent/1.0"


def test_no_proxy_block_is_added_when_none_is_configured():
    """
    Passing proxy=None to new_context is not the same as omitting it in every
    Playwright version; the key should simply not be there.
    """
    assert "proxy" not in AntiDetection.context_kwargs()


def test_a_proxy_server_is_passed_through(monkeypatch):
    monkeypatch.setenv("PROXY_SERVER", "http://proxy.example.com:8080")

    assert AntiDetection.context_kwargs()["proxy"] == {"server": "http://proxy.example.com:8080"}


def test_proxy_credentials_are_added_only_with_a_username(monkeypatch):
    monkeypatch.setenv("PROXY_SERVER", "http://proxy:8080")
    monkeypatch.setenv("PROXY_USERNAME", "user")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")

    proxy = AntiDetection.context_kwargs()["proxy"]
    assert proxy["username"] == "user"
    assert proxy["password"] == "secret"


def test_a_password_without_a_username_is_ignored(monkeypatch):
    """Half-filled proxy credentials are rejected rather than half-applied."""
    monkeypatch.setenv("PROXY_SERVER", "http://proxy:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")

    proxy = AntiDetection.context_kwargs()["proxy"]
    assert "username" not in proxy
    assert "password" not in proxy


def test_a_username_with_no_password_still_sends_an_empty_one(monkeypatch):
    monkeypatch.setenv("PROXY_SERVER", "http://proxy:8080")
    monkeypatch.setenv("PROXY_USERNAME", "user")

    assert AntiDetection.context_kwargs()["proxy"]["password"] == ""


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_proxy_server_is_not_a_proxy(blank, monkeypatch):
    """An env var set to empty is the usual shape of a half-filled .env."""
    monkeypatch.setenv("PROXY_SERVER", blank)

    assert "proxy" not in AntiDetection.context_kwargs()


# ── apply_page_patches ────────────────────────────────────────────────────────

async def test_the_webdriver_patch_is_always_applied():
    """
    Phase 1 has no external dependency and is the one defence that must never
    be conditional — navigator.webdriver is what a bot check reads first.
    """
    page = MagicMock()
    page.add_init_script = AsyncMock()

    await AntiDetection.apply_page_patches(page)

    script = page.add_init_script.await_args.args[0]
    assert "navigator" in script and "webdriver" in script


async def test_a_missing_stealth_library_does_not_stop_the_patching(monkeypatch, caplog):
    """
    playwright-stealth is not in requirements.txt, so this is the default path.
    It must warn and continue — raising here would fail every run on a stock
    install.
    """
    monkeypatch.setitem(sys.modules, "playwright_stealth", None)
    page = MagicMock()
    page.add_init_script = AsyncMock()

    with caplog.at_level("WARNING"):
        await AntiDetection.apply_page_patches(page)

    assert page.add_init_script.await_count == 1, "phase 1 must still have run"
    assert "playwright-stealth not installed" in caplog.text


async def test_stealth_is_applied_when_it_is_available(monkeypatch):
    applied: list = []

    async def fake_stealth(page):
        applied.append(page)

    monkeypatch.setitem(
        sys.modules, "playwright_stealth",
        SimpleNamespace(stealth_async=fake_stealth),
    )
    page = MagicMock()
    page.add_init_script = AsyncMock()

    await AntiDetection.apply_page_patches(page)

    assert applied == [page]


# ── get_playwright ────────────────────────────────────────────────────────────

def test_patchright_is_preferred_when_installed(monkeypatch):
    """
    patchright is a drop-in with a patched TLS fingerprint. Preferring it is the
    whole of phase 5, and the swap is invisible at the call site.
    """
    sentinel = object()
    monkeypatch.setitem(
        sys.modules, "patchright",
        SimpleNamespace(async_api=SimpleNamespace(async_playwright=sentinel)),
    )
    monkeypatch.setitem(
        sys.modules, "patchright.async_api",
        SimpleNamespace(async_playwright=sentinel),
    )

    assert AntiDetection.get_playwright() is sentinel


def test_plain_playwright_is_used_when_patchright_is_absent(monkeypatch):
    """
    The default install. It must not raise.

    The one unit test that genuinely needs the playwright package: it asserts
    get_playwright() hands back that exact object. Everything else in this
    suite runs without it, so the dependency is declared here rather than
    imposed on the whole suite — see docs/universal-runner-plan.md, leak L10.
    """
    async_api = pytest.importorskip(
        "playwright.async_api", reason="playwright is not installed"
    )
    monkeypatch.setitem(sys.modules, "patchright.async_api", None)

    assert AntiDetection.get_playwright() is async_api.async_playwright


# ── detect_captcha ────────────────────────────────────────────────────────────

def _page_matching(*selectors: str):
    """A page whose query_selector finds only the named selectors."""
    page = MagicMock()
    page.query_selector = AsyncMock(
        side_effect=lambda sel: MagicMock() if sel in selectors else None
    )
    return page


async def test_a_clean_page_reports_no_captcha():
    assert await AntiDetection.detect_captcha(_page_matching()) is None


@pytest.mark.parametrize(
    "selector, expected",
    AntiDetection._CAPTCHA_SELECTORS,
)
async def test_each_known_captcha_selector_is_detected(selector, expected):
    assert await AntiDetection.detect_captcha(_page_matching(selector)) == expected


async def test_the_first_matching_selector_wins():
    """
    The list is ordered cheapest-first. Two matches should report the earlier
    one rather than scanning on.
    """
    page = _page_matching("iframe[src*='recaptcha']", ".g-recaptcha")

    assert await AntiDetection.detect_captcha(page) == "reCAPTCHA iframe"


async def test_detection_stops_querying_once_it_finds_one():
    page = _page_matching("iframe[src*='recaptcha']")

    await AntiDetection.detect_captcha(page)

    assert page.query_selector.await_count == 1, "it kept querying after a match"


async def test_a_selector_that_throws_does_not_abort_the_scan():
    """
    A page mid-navigation raises on query_selector. Giving up at the first one
    would miss a CAPTCHA that a later selector would have caught.
    """
    page = MagicMock()

    async def query(sel):
        if sel == "iframe[src*='recaptcha']":
            raise RuntimeError("execution context destroyed")
        return MagicMock() if sel == ".g-recaptcha" else None

    page.query_selector = AsyncMock(side_effect=query)

    assert await AntiDetection.detect_captcha(page) == "reCAPTCHA widget"


async def test_a_page_that_throws_on_everything_reports_no_captcha():
    """None means "did not find one", which is the right answer here — the
    caller proceeds and the step fails on its own terms rather than on ours."""
    page = MagicMock()
    page.query_selector = AsyncMock(side_effect=RuntimeError("page closed"))

    assert await AntiDetection.detect_captcha(page) is None
