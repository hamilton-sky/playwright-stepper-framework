"""
bootstrap/session.py — Domains, and the browser's own session adapter.

Until now main.run() opened the browser itself: start Playwright, launch a
browser, build a context, build a page — all before a StepRunner existed to use
it. That is leak L4 in docs/universal-runner-plan.md, and it is why the only
shipped entry point could not run a workflow that has no browser in it.

The composition root now asks a *domain* for those things instead. A domain is
three factories:

    session   what the run acts on, opened and closed per run
    hooks     what runs around every step (engine/runner/hooks.py)
    shared    a resource several runs in one invocation may share

Only the web domain is registered here. T8's noop domain registers itself the
same way, and a real second domain — AWS, HTTP, a database — would too.

    register_domain(Domain(
        name="aws",
        session=AwsSession,
        hooks=no_hooks,
        shared=no_shared,
    ))

`shared` exists for one real case: `run_data_rows` runs the same workflow once
per data row and reuses a single browser across all of them. That is an
optimisation the web domain offers, not a property of the session contract, so
it lives behind a domain factory rather than in the runner or in main.py. A
domain with nothing to share uses `no_shared`, which yields None.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from stepper.engine.runner.hooks import StepHook, default_web_hooks

logger = logging.getLogger(__name__)


# ── The browser's session adapter ─────────────────────────────────────────────

class WebSession:
    """
    SessionAdapter for the browser domain — see engine/session.py.

    open() returns a Playwright Page, which is what every web action and every
    POM already expects as its first argument, so nothing downstream changes.

    Owns the whole stack — Playwright, browser, context, page — unless it is
    handed a browser through `shared`, in which case it owns only the context
    and the page and leaves the browser to whoever opened it.
    """

    domain = "web"

    def __init__(self, cfg, settings, test_reporter=None, *, shared=None):
        self._cfg           = cfg
        self._settings      = settings
        self._test_reporter = test_reporter
        self._browser       = shared
        self._owns_browser  = shared is None
        self._pw            = None
        self.context        = None
        self.page           = None

    async def open(self):
        """Start what is not already running and hand back a live page."""
        from stepper.engine.browser.anti_detection import AntiDetection
        from stepper.bootstrap.infra import launch_browser

        if self._owns_browser:
            async_playwright = AntiDetection.get_playwright()
            self._pw = await async_playwright().start()
            self._browser = await launch_browser(
                self._pw, self._settings.browser,
                self._cfg.headless, self._settings.slow_mo,
            )

        context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
        context_kwargs.update(AntiDetection.context_kwargs())

        storage = self._settings.storage_state_path
        if storage and Path(str(storage)).exists():
            context_kwargs["storage_state"] = str(storage)
            logger.info(f"Loaded session from {storage}")

        reporter = self._test_reporter
        if self._cfg.record_video and reporter and reporter.manager.current_test_dir:
            videos_dir = reporter.manager.current_test_dir / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"]  = str(videos_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 800}
            logger.info(f"Recording video → {videos_dir}")

        self.context = await self._browser.new_context(**context_kwargs)
        self.page    = await self.context.new_page()
        await AntiDetection.apply_page_patches(self.page)
        return self.page

    async def close(self) -> None:
        """
        Close what this session opened, in the order run() used to close it.

        Nested finallys rather than a try/except each: every stage still runs
        when an earlier one fails — closing the context is what flushes a
        recorded video, and a browser left running outlives the process — but
        the first failure still propagates, as it did before.
        """
        try:
            if self.context is not None:
                await self.context.close()
        finally:
            try:
                if self._owns_browser and self._browser is not None:
                    await self._browser.close()
            finally:
                if self._owns_browser and self._pw is not None:
                    await self._pw.stop()


@asynccontextmanager
async def web_shared_browser(cfg, settings):
    """One Playwright browser for several runs in one invocation."""
    from stepper.engine.browser.anti_detection import AntiDetection
    from stepper.bootstrap.infra import launch_browser

    async_playwright = AntiDetection.get_playwright()
    async with async_playwright() as pw:
        browser = await launch_browser(pw, settings.browser,
                                       cfg.headless, settings.slow_mo)
        try:
            yield browser
        finally:
            await browser.close()


# ── Domains with nothing to open ──────────────────────────────────────────────

def no_hooks(screenshots_dir=None) -> list[StepHook]:
    """For a domain with nothing to do around a step."""
    return []


@asynccontextmanager
async def no_shared(cfg=None, settings=None):
    """For a domain with nothing to share between runs."""
    yield None


# ── The registry ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Domain:
    """
    What the composition root needs from a domain to build one run.

    session : (cfg, settings, test_reporter, *, shared) -> SessionAdapter
    hooks   : (screenshots_dir) -> list[StepHook]
    shared  : (cfg, settings) -> async context manager yielding an opaque handle
    """

    name: str
    session: Callable[..., Any]
    hooks: Callable[..., list] = field(default=no_hooks)
    shared: Callable[..., Any] = field(default=no_shared)


_DOMAINS: dict[str, Domain] = {}


def register_domain(domain: Domain) -> Domain:
    """
    Add a domain. Re-registering the same name replaces it, which is what a
    test that swaps in a fake domain wants; registering a *different* domain
    under a name already taken is how two domains silently shadow each other,
    so it is not allowed.
    """
    existing = _DOMAINS.get(domain.name)
    if existing is not None and existing != domain:
        raise ValueError(
            f"Domain '{domain.name}' is already registered to "
            f"{existing.session!r}. Pick another name, or pass the same Domain."
        )
    _DOMAINS[domain.name] = domain
    logger.debug(f"Registered domain: {domain.name}")
    return domain


def get_domain(name: str) -> Domain:
    domain = _DOMAINS.get(name)
    if domain is None:
        raise ValueError(
            f"Unknown domain: '{name}'. Registered: {sorted(_DOMAINS)}"
        )
    return domain


def domain_names() -> list[str]:
    return sorted(_DOMAINS)


register_domain(Domain(
    name="web",
    session=WebSession,
    hooks=default_web_hooks,
    shared=web_shared_browser,
))
