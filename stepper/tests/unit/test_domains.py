"""
Tests for the domain seam at the composition root (ticket T3).

main.run() used to launch Playwright itself, before a StepRunner existed to use
the page — leak L4. It now asks a domain for three things: a session to open, a
set of per-step hooks, and whatever several runs in one invocation can share.
Only the web domain is registered by default, and these pin that the seam is
real rather than a browser launch wearing a new name.

No browser here: WebSession is exercised through fakes for its context and
browser, which is enough to pin the lifecycle it owns.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.bootstrap.session import (
    Domain, WebSession, get_domain, domain_names, no_hooks, no_shared,
    register_domain,
)
from stepper.engine.runner.hooks import CaptchaHook, ScreenshotHook
from stepper.main import PreparedRun, RunConfig, build_pipeline, build_session


# ── The registry ──────────────────────────────────────────────────────────────

def test_the_web_domain_ships_registered():
    assert "web" in domain_names()
    assert get_domain("web").session is WebSession


def test_the_web_domain_supplies_the_browser_hooks():
    installed = [type(h) for h in get_domain("web").hooks(None)]

    assert installed == [CaptchaHook, ScreenshotHook]


def test_an_unknown_domain_names_the_ones_that_exist():
    with pytest.raises(ValueError, match="Unknown domain: 'aws'"):
        get_domain("aws")


def test_a_domain_can_be_registered_and_found():
    domain = Domain(name="test_probe", session=MagicMock())

    register_domain(domain)

    assert get_domain("test_probe") is domain


def test_registering_the_same_domain_twice_is_fine():
    domain = Domain(name="test_idempotent", session=MagicMock())

    register_domain(domain)
    register_domain(domain)

    assert get_domain("test_idempotent") is domain


def test_two_different_domains_cannot_share_a_name():
    register_domain(Domain(name="test_clash", session=MagicMock()))

    with pytest.raises(ValueError, match="already registered"):
        register_domain(Domain(name="test_clash", session=MagicMock()))


def test_a_domain_defaults_to_no_hooks_and_nothing_shared():
    domain = Domain(name="test_bare", session=MagicMock())

    assert domain.hooks is no_hooks
    assert domain.shared is no_shared
    assert domain.hooks(None) == []


async def test_nothing_shared_yields_nothing():
    async with no_shared(None, None) as shared:
        assert shared is None


# ── WebSession's lifecycle ────────────────────────────────────────────────────

def _web_session(**kwargs):
    cfg = RunConfig(task="probe", record_video=False)
    settings = MagicMock()
    settings.storage_state_path = None
    return WebSession(cfg, settings, test_reporter=None, **kwargs)


async def test_a_shared_browser_is_used_but_not_owned(monkeypatch):
    from stepper.engine.browser.anti_detection import AntiDetection
    monkeypatch.setattr(AntiDetection, "apply_page_patches", AsyncMock())

    browser = MagicMock()
    context = MagicMock()
    context.close = AsyncMock()
    context.new_page = AsyncMock(return_value=MagicMock())
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    session = _web_session(shared=browser)
    await session.open()
    await session.close()

    context.close.assert_awaited_once()          # this row's context goes
    browser.close.assert_not_awaited()           # the shared browser stays


async def test_an_owned_browser_is_closed_with_the_session():
    session = _web_session()
    session._owns_browser = True
    session.context = MagicMock(close=AsyncMock())
    session._browser = MagicMock(close=AsyncMock())
    session._pw = MagicMock(stop=AsyncMock())

    await session.close()

    session.context.close.assert_awaited_once()
    session._browser.close.assert_awaited_once()
    session._pw.stop.assert_awaited_once()


async def test_a_failure_closing_the_context_still_closes_the_browser():
    """
    Closing the context is what flushes a recorded video, and a browser left
    running outlives the process. Neither may be skipped because the other
    failed — but the failure still has to surface.
    """
    session = _web_session()
    session._owns_browser = True
    session.context = MagicMock(close=AsyncMock(side_effect=RuntimeError("video")))
    session._browser = MagicMock(close=AsyncMock())
    session._pw = MagicMock(stop=AsyncMock())

    with pytest.raises(RuntimeError, match="video"):
        await session.close()

    session._browser.close.assert_awaited_once()
    session._pw.stop.assert_awaited_once()


async def test_closing_a_session_that_never_opened_is_harmless():
    await _web_session().close()


async def test_the_web_session_names_its_domain():
    assert WebSession.domain == "web"
    assert _web_session().domain == "web"


# ── build_session / build_pipeline pick up the domain ─────────────────────────

class FakeSession:
    domain = "test_fake"

    def __init__(self, cfg, settings, test_reporter=None, *, shared=None):
        self.cfg, self.shared = cfg, shared
        self.context = "the-context"
        self.opened = self.closed = 0

    async def open(self):
        self.opened += 1
        return "the-target"

    async def close(self):
        self.closed += 1


@pytest.fixture(scope="module")
def fake_domain():
    """
    Module-scoped on purpose. register_domain refuses to replace a domain with
    a *different* one under the same name, and a function-scoped fixture would
    build a new Domain (and a new hooks lambda) for every test — tripping the
    very guard test_two_different_domains_cannot_share_a_name pins.
    """
    marker = MagicMock(name="hook")
    domain = Domain(
        name="test_fake",
        session=FakeSession,
        hooks=lambda screenshots_dir=None: [marker],
    )
    register_domain(domain)
    return domain, marker


@pytest.fixture
def prepared(tmp_path):
    return PreparedRun(
        cfg=RunConfig(task="probe", domain="test_fake"),
        steps=[],
        settings=MagicMock(),
        resolver=MagicMock(),
        reporter=MagicMock(),
        test_reporter=None,
        registry=MagicMock(),
        screenshots_dir=tmp_path,
        subflow_action=MagicMock(),
    )


def test_build_session_asks_the_configured_domain(fake_domain, prepared):
    session = build_session(prepared)

    assert isinstance(session, FakeSession)
    assert session.shared is None


def test_build_session_passes_the_shared_handle_through(fake_domain, prepared):
    session = build_session(prepared, shared="a-browser")

    assert session.shared == "a-browser"


async def test_build_pipeline_opens_the_session_once(fake_domain, prepared):
    session = build_session(prepared)

    pipeline = await build_pipeline(prepared, session)

    assert session.opened == 1
    assert pipeline.page == "the-target"
    assert pipeline.session is session


async def test_build_pipeline_gives_the_runner_the_domains_hooks(fake_domain, prepared):
    """
    Keyed by domain since M3, so a step runs its own domain's hooks and no
    others — the whole point of the change.
    """
    _domain, marker = fake_domain
    session = build_session(prepared)

    pipeline = await build_pipeline(prepared, session)

    assert pipeline.runner._hooks["test_fake"] == [marker]


async def test_every_domains_hooks_are_present_not_just_the_primary(fake_domain, prepared):
    """
    A workflow may name a step from another domain, so that domain's hooks have
    to be there to run — or not run, in the case of a domain with none.
    """
    session = build_session(prepared)

    pipeline = await build_pipeline(prepared, session)

    assert "web" in pipeline.runner._hooks
    assert pipeline.runner._hooks["noop"] == []


async def test_build_pipeline_does_not_close_what_it_opened(fake_domain, prepared):
    """The caller owns the session's lifetime — run() closes it in a finally."""
    session = build_session(prepared)

    await build_pipeline(prepared, session)

    assert session.closed == 0


async def test_the_pipeline_keeps_the_context_for_the_session_save(fake_domain, prepared):
    session = build_session(prepared)

    pipeline = await build_pipeline(prepared, session)

    assert pipeline.context == "the-context"


def test_a_run_defaults_to_the_web_domain():
    assert RunConfig(task="probe").domain == "web"
