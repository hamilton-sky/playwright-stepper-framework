from __future__ import annotations
import asyncio


class BasePage:
    def __init__(self, driver, base_url: str, delays=None, page=None, resolver=None):
        self._driver = driver
        self.base_url = base_url
        self._page = page
        self._resolver = resolver
        if delays is not None:
            self.delays = delays
        else:
            from goodreads.config import load_settings
            self.delays = load_settings().delays

    @property
    def url(self) -> str:
        raise NotImplementedError

    async def open(self) -> None:
        await self._driver.goto(self.url, wait_until="domcontentloaded")
        await asyncio.sleep(self.delays.page_load_wait_ms / 1000)
        await self._driver.wait_for_load_state("networkidle")
        await self.wait_for_ready()

    async def wait_for_ready(self) -> None:
        return None
