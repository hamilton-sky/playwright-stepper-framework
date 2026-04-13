"""
pages/base_page.py — Base class for all OpenLibrary pure POMs.

Extends poms.shared.base_page.BasePage with OpenLibrary-specific concerns:
  - delays (rate-limiting config value object)
  - open() override that honours page_load_wait_ms

No src/ imports. No framework imports.

Resolver is accepted as an optional duck-typed argument — injected by the
Stepper glue layer at runtime. BasePage never imports from src/.
"""
from __future__ import annotations
import asyncio
import logging

from poms.shared.base_page import BasePage as SharedBasePage

logger = logging.getLogger(__name__)


class BasePage(SharedBasePage):
    """
    Base for all OpenLibrary page objects.

    Adds delays support on top of the shared resolver-aware helpers.

    Two operating modes — determined by whether resolver is injected:

      driver-only  (resolver=None)
        All interactions use PlaywrightDriver CSS selectors directly.
        Used by: api.py direct calls, standalone scripts.

      resolver-enhanced  (resolver=ElementResolver instance)
        Interactive element finding goes through the full 10-stage cascade.
        Falls back to driver if resolver returns low confidence.
        Used by: Stepper glue layer (_execute injects page + resolver).

    Subclasses define:
      - url property
      - wait_for_ready() override (optional)
      - domain methods (search, collect, add_to_list, etc.)
    """

    def __init__(self, driver, base_url: str, delays=None,
                 page=None, resolver=None):
        from poms.shared.interfaces import Delays
        super().__init__(driver, base_url, page=page, resolver=resolver)
        self.delays = delays if delays is not None else Delays()

    async def open(self) -> None:
        await self._driver.goto(self.url, wait_until="domcontentloaded")
        await asyncio.sleep(self.delays.page_load_wait_ms / 1000)
        # networkidle can hang indefinitely on pages with lazy-loading or
        # analytics polling — domcontentloaded is reliable enough, and
        # each subclass wait_for_ready() handles page-specific readiness.
        await self.wait_for_ready()
