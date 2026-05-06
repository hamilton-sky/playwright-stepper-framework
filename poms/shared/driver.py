"""
shared/driver.py — Playwright isolation wrapper.

This is the ONLY file in the automation module that imports from playwright.
All page objects, auth, and performance code depend on IBrowserDriver (interface),
not on Playwright's Page directly.

Pattern: Adapter
  IBrowserDriver   — the interface (in shared/interfaces.py)
  PlaywrightDriver — this file, adapts Playwright's Page to IBrowserDriver
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Page, ElementHandle

from poms.shared.interfaces import IBrowserDriver, IBrowserLauncher, IElementHandle

logger = logging.getLogger(__name__)

_TRANSIENT_GOTO_ERRORS = (
    "ERR_EMPTY_RESPONSE",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_TIMED_OUT",
    "Timeout",
    "TimeoutError",
)


class PlaywrightElementHandle(IElementHandle):
    """Wraps a single Playwright ElementHandle."""

    def __init__(self, handle: ElementHandle) -> None:
        self._h = handle

    async def inner_text(self) -> str:
        return await self._h.inner_text()

    async def get_attribute(self, name: str) -> str | None:
        return await self._h.get_attribute(name)

    async def click(self) -> None:
        await self._h.click()
        
    async def hover(self, timeout: int = 30_000) -> None:
        """Pass the timeout through to the real Playwright handle."""
        await self._h.hover(timeout=timeout)
        
    async def bounding_box(self):
        """Returns the bounding box of the element."""
        return await self._h.bounding_box()

    async def query_selector(self, selector: str) -> IElementHandle | None:
        h = await self._h.query_selector(selector)
        return PlaywrightElementHandle(h) if h else None


class PlaywrightDriver(IBrowserDriver):
    """
    Wraps Playwright's Page object behind IBrowserDriver.

    DIP: Only glue-layer wiring points instantiate this class.
    Everything else receives an IBrowserDriver.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, url: str, *,
                   wait_until: str = "domcontentloaded",
                   timeout: int = 30_000) -> None:
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await self._page.goto(url, wait_until=wait_until, timeout=timeout)
                return
            except Exception as exc:
                last_error = exc
                message = str(exc)
                transient = any(token in message for token in _TRANSIENT_GOTO_ERRORS)
                if not transient or attempt == attempts:
                    raise
                delay_s = 1.5 * attempt
                logger.warning(
                    "Navigation to %s failed on attempt %d/%d (%s); retrying in %.1fs",
                    url,
                    attempt,
                    attempts,
                    message.splitlines()[0],
                    delay_s,
                )
                await asyncio.sleep(delay_s)

        if last_error is not None:
            raise last_error

    async def fill(self, selector: str, value: str, *, timeout: int = 15_000) -> None:
        await self._page.fill(selector, value, timeout=timeout)

    async def click(self, selector: str, *, timeout: int = 10_000) -> None:
        await self._page.click(selector, timeout=timeout)

    async def press(self, selector: str, key: str) -> None:
        locator = self._page.locator(selector)
        await locator.press(key)

    async def query_selector(self, selector: str) -> IElementHandle | None:
        h = await self._page.query_selector(selector)
        return PlaywrightElementHandle(h) if h else None

    async def query_selector_all(self, selector: str) -> list[IElementHandle]:
        handles = await self._page.query_selector_all(selector)
        return [PlaywrightElementHandle(h) for h in handles]

    async def wait_for_selector(self, selector: str, *,
                                timeout: int = 30_000) -> IElementHandle | None:
        h = await self._page.wait_for_selector(selector, timeout=timeout)
        return PlaywrightElementHandle(h) if h else None

    async def wait_for_load_state(self, state: str) -> None:
        await self._page.wait_for_load_state(state)

    async def screenshot(self, path: str) -> None:
        await self._page.screenshot(path=path, animations="disabled", timeout=10_000)

    async def evaluate(self, js_code: str):
        return await self._page.evaluate(js_code)

    async def locator_count(self, selector: str) -> int:
        return await self._page.locator(selector).count()

    async def get_by_text(self, text: str, *, exact: bool = True):
        return self._page.get_by_text(text, exact=exact).first

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = True):
        kwargs = {"name": name, "exact": exact} if name else {}
        return self._page.get_by_role(role, **kwargs)

    def get_by_label(self, text: str, *, exact: bool = True):
        return self._page.get_by_label(text, exact=exact)

    def get_by_placeholder(self, text: str, *, exact: bool = True):
        return self._page.get_by_placeholder(text, exact=exact)

    def get_by_test_id(self, test_id: str):
        return self._page.get_by_test_id(test_id)

    def locator(self, selector: str):
        return self._page.locator(selector)

    @property
    def current_url(self) -> str:
        return self._page.url


class PlaywrightBrowserLauncher(IBrowserLauncher):
    """
    Concrete IBrowserLauncher — spawns isolated Playwright browsers.

    Owns the headless flag and storage_state path so the engine never
    needs to know about either.
    """

    def __init__(self, headless: bool = True, storage_state_path: Path | None = None):
        self._headless = headless
        self._storage_state_path = storage_state_path

    async def create_page(self) -> tuple[Any, Any]:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=self._headless)
        ctx_kwargs: dict = {}
        if self._storage_state_path and self._storage_state_path.exists():
            ctx_kwargs["storage_state"] = str(self._storage_state_path)
        ctx = await browser.new_context(**ctx_kwargs)
        page = await ctx.new_page()
        return (pw, browser), page

    async def release(self, handle: Any) -> None:
        pw, browser = handle
        await browser.close()
        await pw.stop()
