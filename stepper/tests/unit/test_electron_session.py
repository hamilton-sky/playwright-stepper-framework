"""
Attaching to a running Electron app instead of launching a browser.

Ported from hamilton/generation-pipeline, which had it as a bare
`launch_electron_cdp(port)` returning a BrowserContext. Three things were
wrong with that shape against today's architecture, and each has a test here.

**It leaked Playwright.** The function started a Playwright handle and returned
only the context, so on the success path nothing could ever stop it — `pw.stop()`
appeared on the timeout path alone. A SessionAdapter is the shape that makes
that impossible rather than remembered.

**It would have broken the hermetic guarantee.** It lived in
`engine/browser/` and imported `playwright.async_api` at module scope. Nothing
under `engine/browser/` does that, because a db-only or noop run asserts
Playwright never reaches `sys.modules`.

**Its failure took 30 seconds to arrive.** "Is Electron running with
--remote-debugging-port?" is answered by a TCP connect in milliseconds, and
since M5 there is a preflight slot for exactly that answer.

It stays on the **web** domain. Electron renders a DOM, so every web action and
the whole resolver cascade apply unchanged; and every engine action declares
`domain = "web"`, so an `electron` domain would route `click` to a browser this
run never asked for.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.bootstrap.infra import (ELECTRON_PORT_VAR, ElectronConnectError,
                                     connect_electron_cdp, electron_port_open)
from stepper.bootstrap.session import (ElectronSession, WebSession,
                                       electron_cdp_port, get_domain, web_session)


@pytest.fixture(autouse=True)
def no_ambient_port(monkeypatch):
    """No test here may be steered by a port set in the real environment."""
    monkeypatch.delenv(ELECTRON_PORT_VAR, raising=False)
    monkeypatch.delenv("STEPPER_ELECTRON_TIMEOUT_MS", raising=False)


def _connected(contexts=None, pages=None):
    """A Playwright double: async_playwright() -> pw -> chromium.connect_over_cdp."""
    page    = MagicMock()
    context = MagicMock(pages=list(pages) if pages is not None else [page])
    browser = MagicMock(contexts=list(contexts) if contexts is not None else [context])
    browser.close = AsyncMock()
    context.new_page = AsyncMock(return_value=page)

    pw = MagicMock()
    pw.chromium.connect_over_cdp = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()
    return pw, browser, context, page


def _patch_playwright(monkeypatch, pw):
    started = MagicMock()
    started.start = AsyncMock(return_value=pw)
    monkeypatch.setattr(
        "stepper.engine.browser.anti_detection.AntiDetection.get_playwright",
        staticmethod(lambda: MagicMock(return_value=started)),
    )


# ── Choosing the session ──────────────────────────────────────────────────────

def test_without_the_port_the_web_domain_launches_a_browser():
    assert electron_cdp_port() is None
    assert isinstance(web_session(None, None), WebSession)


def test_with_the_port_the_web_domain_attaches_instead(monkeypatch):
    monkeypatch.setenv(ELECTRON_PORT_VAR, "9222")

    assert electron_cdp_port() == 9222
    assert isinstance(web_session(None, None), ElectronSession)


def test_a_port_that_is_not_a_number_falls_back_rather_than_crashing(monkeypatch):
    """
    A stale value in someone's .env degrades to the normal behaviour, which is
    what browser_launch_kwargs does with a bad BROWSER_EXECUTABLE_PATH.
    """
    monkeypatch.setenv(ELECTRON_PORT_VAR, "not-a-port")

    assert electron_cdp_port() is None
    assert isinstance(web_session(None, None), WebSession)


def test_electron_is_still_the_web_domain():
    """
    Every engine action declares domain="web". A domain of its own would route
    `click` to a launched browser rather than to the app.
    """
    assert ElectronSession.domain == "web"
    assert ElectronSession(None, None, port=1).domain == "web"


# ── Preflight: the 30-second wait becomes a plan-time refusal ────────────────

def test_a_closed_port_is_reported_before_anything_opens(monkeypatch):
    monkeypatch.setenv(ELECTRON_PORT_VAR, "59999")          # nothing listens here

    reasons = get_domain("web").preflight(None, None)

    assert len(reasons) == 1
    assert "59999" in reasons[0] and "--remote-debugging-port" in reasons[0]


def test_an_open_port_is_ready(monkeypatch):
    monkeypatch.setenv(ELECTRON_PORT_VAR, "9222")
    monkeypatch.setattr("stepper.bootstrap.infra.electron_port_open", lambda p, **k: True)

    assert get_domain("web").preflight(None, None) == []


def test_without_the_port_preflight_still_checks_the_browser():
    """The Electron path must not disable the check that was already there."""
    from stepper.bootstrap.infra import browser_preflight

    assert get_domain("web").preflight(None, None) == browser_preflight("chromium")


def test_the_port_check_is_a_plain_tcp_connect():
    assert electron_port_open(59999) is False


# ── Connecting ────────────────────────────────────────────────────────────────

async def test_a_successful_attach_returns_both_handles(monkeypatch):
    """
    Both, not just the browser. A function that returns only the browser is how
    the original leaked its Playwright handle — nothing downstream could stop it.
    """
    pw, browser, _c, _p = _connected()
    _patch_playwright(monkeypatch, pw)

    got_pw, got_browser = await connect_electron_cdp(port=9222)

    assert (got_pw, got_browser) == (pw, browser)
    pw.chromium.connect_over_cdp.assert_awaited_once_with("http://localhost:9222")
    pw.stop.assert_not_awaited(), "a live connection must not stop Playwright"


async def test_a_browser_with_no_context_yet_is_retried(monkeypatch):
    """
    "Attached, but the app has not built a window yet" is a transient state
    during startup, not success. Returning it would hand out contexts[0] and
    raise IndexError somewhere far away.
    """
    pw, browser, _c, _p = _connected(contexts=[])
    _patch_playwright(monkeypatch, pw)

    with pytest.raises(ElectronConnectError) as exc:
        await connect_electron_cdp(port=9222, timeout_ms=1)

    assert "no context yet" in str(exc.value)
    assert browser.close.await_count >= 1, "each contextless attempt is released"


async def test_a_refused_connection_times_out_with_the_port_named(monkeypatch):
    pw, _b, _c, _p = _connected()
    pw.chromium.connect_over_cdp = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    _patch_playwright(monkeypatch, pw)

    with pytest.raises(ElectronConnectError) as exc:
        await connect_electron_cdp(port=9222, timeout_ms=1)

    assert "9222" in str(exc.value)
    assert "--remote-debugging-port" in str(exc.value)
    assert "refused" in str(exc.value), "the last real error is worth keeping"


async def test_playwright_is_stopped_when_the_attach_fails(monkeypatch):
    """The failure path must not leak either — it is the one the old code got right."""
    pw, _b, _c, _p = _connected()
    pw.chromium.connect_over_cdp = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    _patch_playwright(monkeypatch, pw)

    with pytest.raises(ElectronConnectError):
        await connect_electron_cdp(port=9222, timeout_ms=1)

    pw.stop.assert_awaited_once()


# ── The session's lifecycle ───────────────────────────────────────────────────

async def test_open_returns_the_page_already_on_screen(monkeypatch):
    """
    An Electron window *is* a page. Calling new_page() would put a blank tab in
    front of the application rather than driving what the person is looking at.
    """
    pw, _b, context, page = _connected()
    _patch_playwright(monkeypatch, pw)
    session = ElectronSession(None, None, port=9222)

    assert await session.open() is page
    context.new_page.assert_not_awaited()


async def test_a_context_with_no_pages_gets_one(monkeypatch):
    pw, _b, context, _p = _connected(pages=[])
    _patch_playwright(monkeypatch, pw)

    await ElectronSession(None, None, port=9222).open()

    context.new_page.assert_awaited_once()


async def test_close_disconnects_and_releases_playwright(monkeypatch):
    pw, browser, _c, _p = _connected()
    _patch_playwright(monkeypatch, pw)
    session = ElectronSession(None, None, port=9222)
    await session.open()

    await session.close()

    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()


async def test_close_never_touches_the_app_s_own_context_or_page(monkeypatch):
    """
    The asymmetry with WebSession, and the reason this is not a copy of it.
    WebSession launched everything it holds; this attached to a process someone
    else started. Closing contexts[0] would close the window on their screen.
    """
    pw, _b, context, page = _connected()
    context.close = AsyncMock()
    page.close = AsyncMock()
    _patch_playwright(monkeypatch, pw)
    session = ElectronSession(None, None, port=9222)
    await session.open()

    await session.close()

    context.close.assert_not_awaited()
    page.close.assert_not_awaited()


async def test_closing_an_unopened_session_is_harmless():
    """close_all runs in a finally; a session that never opened must not raise."""
    await ElectronSession(None, None, port=9222).close()


async def test_playwright_is_stopped_even_when_the_disconnect_raises(monkeypatch):
    """
    Nested finallys, the shape WebSession.close uses: the later step still runs
    when an earlier one fails, and the first failure still propagates.
    """
    pw, browser, _c, _p = _connected()
    browser.close = AsyncMock(side_effect=RuntimeError("already gone"))
    _patch_playwright(monkeypatch, pw)
    session = ElectronSession(None, None, port=9222)
    await session.open()

    with pytest.raises(RuntimeError):
        await session.close()

    pw.stop.assert_awaited_once()


async def test_the_session_satisfies_the_adapter_protocol():
    from stepper.engine.session import SessionAdapter

    assert isinstance(ElectronSession(None, None, port=1), SessionAdapter)
