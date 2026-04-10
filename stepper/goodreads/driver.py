from __future__ import annotations

from playwright.async_api import Page, ElementHandle

from interfaces import IBrowserDriver, IElementHandle


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

    async def query_selector(self, selector: str) -> IElementHandle | None:
        h = await self._h.query_selector(selector)
        return PlaywrightElementHandle(h) if h else None


class PlaywrightDriver(IBrowserDriver):
    """Wraps Playwright's Page behind IBrowserDriver."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def goto(self, url: str, *, wait_until: str = "domcontentloaded") -> None:
        await self._page.goto(url, wait_until=wait_until)

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._page.click(selector)

    async def press(self, selector: str, key: str) -> None:
        locator = self._page.locator(selector)
        await locator.press(key)

    async def query_selector(self, selector: str) -> IElementHandle | None:
        h = await self._page.query_selector(selector)
        return PlaywrightElementHandle(h) if h else None

    async def query_selector_all(self, selector: str) -> list[IElementHandle]:
        handles = await self._page.query_selector_all(selector)
        return [PlaywrightElementHandle(h) for h in handles]

    async def wait_for_selector(self, selector: str, *, timeout: int = 30_000) -> IElementHandle | None:
        h = await self._page.wait_for_selector(selector, timeout=timeout)
        return PlaywrightElementHandle(h) if h else None

    async def wait_for_load_state(self, state: str) -> None:
        await self._page.wait_for_load_state(state)

    async def screenshot(self, path: str) -> None:
        await self._page.screenshot(path=path)

    async def evaluate(self, js_code: str):
        return await self._page.evaluate(js_code)

    async def locator_count(self, selector: str) -> int:
        return await self._page.locator(selector).count()

    async def get_by_text(self, text: str, *, exact: bool = True):
        return self._page.get_by_text(text, exact=exact).first

    @property
    def current_url(self) -> str:
        return self._page.url
