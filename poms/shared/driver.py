"""
shared/driver.py — Playwright isolation wrapper.

This is the ONLY file in the automation module that imports from playwright,
and it does so lazily: `Page` and `ElementHandle` are annotations, so they sit
under TYPE_CHECKING, and `async_playwright` is imported inside the one method
that launches anything. Importing this module therefore costs no browser —
which is what lets a run with no browser in it prove that, by asserting
"playwright" never lands in sys.modules.

All page objects, auth, and performance code depend on IBrowserDriver (interface),
not on Playwright's Page directly.

Pattern: Adapter
  IBrowserDriver   — the interface (in shared/interfaces.py)
  PlaywrightDriver — this file, adapts Playwright's Page to IBrowserDriver
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:                       # annotations only — see module docstring
    from playwright.async_api import Page, ElementHandle

from poms.shared.interfaces import IBrowserDriver, IBrowserLauncher, IElementHandle

logger = logging.getLogger(__name__)

#: Env var pointing at a browser binary to use instead of the one Playwright
#: downloaded for itself.
_EXECUTABLE_PATH_VAR = "BROWSER_EXECUTABLE_PATH"


def browser_launch_kwargs() -> dict:
    """
    Extra kwargs for browser_type.launch(), empty unless an override is set.

    Playwright refuses to launch unless the exact chromium revision its version
    expects is on disk. That is usually what you want — but a prebuilt
    container often ships one specific revision and no way to download another,
    so a version bump here turns every run there into "please run playwright
    install", which is the one thing that image cannot do.

    requirements.txt pins the version whose revision matches the image we run
    in. This is the escape hatch for when it does not:

        BROWSER_EXECUTABLE_PATH=/opt/pw-browsers/chromium python stepper/main.py run ...

    A path that does not exist is ignored with a warning rather than failing the
    launch, so a stale value in someone's .env degrades to the normal behaviour
    instead of breaking every run.
    """
    raw = os.environ.get(_EXECUTABLE_PATH_VAR, "").strip()
    if not raw:
        return {}
    if not Path(raw).exists():
        logger.warning(
            "%s=%s does not exist — falling back to Playwright's own browser",
            _EXECUTABLE_PATH_VAR, raw,
        )
        return {}
    logger.info("Using browser executable %s (%s)", raw, _EXECUTABLE_PATH_VAR)
    return {"executable_path": raw}


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
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

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
        browser = await pw.chromium.launch(headless=self._headless,
                                           **browser_launch_kwargs())
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
