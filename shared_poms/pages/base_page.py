"""
pages/base_page.py — Base class for all OpenLibrary pure POMs.

Imports:
  - openlibrary_exam.config  (Delays — value object)

No src/ imports. No framework imports.

Resolver is accepted as an optional duck-typed argument — injected by the
Stepper glue layer at runtime. BasePage never imports from src/.
"""
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)

CONFIDENCE_AUTO = 0.80
CONFIDENCE_WARN = 0.50


class BasePage:
    """
    Base for all OpenLibrary page objects.

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
        from shared_poms.interfaces import Delays
        self._driver   = driver
        self.base_url  = base_url
        self._page     = page      # Playwright Page — for resolver
        self._resolver = resolver  # ElementResolver — 10-stage cascade (optional)
        if delays is not None:
            self.delays = delays
        else:
            # Fallback to default delays if not provided
            self.delays = delays or Delays()

    @property
    def url(self) -> str:
        raise NotImplementedError

    async def open(self) -> None:
        await self._driver.goto(self.url, wait_until="domcontentloaded")
        await asyncio.sleep(self.delays.page_load_wait_ms / 1000)
        # networkidle can hang indefinitely on pages with lazy-loading or
        # analytics polling — domcontentloaded is reliable enough, and
        # each subclass wait_for_ready() handles page-specific readiness.
        await self.wait_for_ready()

    async def wait_for_ready(self) -> None:
        """Override in subclass for page-specific readiness check."""

    # ── Resolver-aware interaction helpers ────────────────────────────────────

    async def _resolve_and_click(
        self, cfg: dict, description: str = "", js_click: bool = False
    ) -> bool:
        """
        Find an element and click it.
        With resolver → full 10-stage cascade.
        Without resolver → driver CSS fallback.
        Returns True on success, False if element not found.
        """
        if self._resolver and self._page:
            result = await self._resolver.resolve(self._page, cfg, description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        f"Medium confidence {result.confidence:.0%} on click — proceeding"
                    )
                try:
                    if js_click:
                        await result.locator.first.evaluate("el => el.click()")
                    else:
                        await result.locator.scroll_into_view_if_needed(timeout=5_000)
                        await result.locator.click(timeout=5_000)
                    logger.info(
                        f"✓ click via {result.method} ({result.confidence:.0%})"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Resolver found element but click failed: {e}")
                    return False
            logger.warning(f"Resolver could not find element for click: {cfg}")
            return False

        # Driver fallback — CSS only
        css = cfg.get("css") or (f"#{cfg['id']}" if cfg.get("id") else None)
        if css:
            try:
                await self._driver.click(css)
                return True
            except Exception:
                return False
        return False

    # ── Resolver-aware priority helpers ─────────────────────────────────────

    @staticmethod
    def _ordered_cfgs(cfgs: list[dict]) -> list[dict]:
        """
        Return cfgs ordered by explicit priority (lower first), otherwise
        preserve original order. Each cfg may include "priority".
        """
        indexed = list(enumerate(cfgs))

        def sort_key(item):
            idx, cfg = item
            if "priority" in cfg:
                return (0, cfg["priority"], idx)
            return (1, idx)

        return [cfg for _, cfg in sorted(indexed, key=sort_key)]

    async def _resolve_and_fill(
        self, cfg: dict, value: str, description: str = ""
    ) -> bool:
        """
        Find an element and fill it.
        With resolver → full 10-stage cascade.
        Without resolver → driver CSS fallback.
        Returns True on success, False if element not found.
        """
        if self._resolver and self._page:
            result = await self._resolver.resolve(self._page, cfg, description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        f"Medium confidence {result.confidence:.0%} on fill — proceeding"
                    )
                try:
                    await result.locator.scroll_into_view_if_needed(timeout=5_000)
                    await result.locator.first.fill(value, timeout=5_000)
                    logger.info(
                        f"✓ fill via {result.method} ({result.confidence:.0%})"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Resolver found element but fill failed: {e}")
                    return False
            logger.warning(f"Resolver could not find element for fill: {cfg}")
            return False

        # Driver fallback — CSS only
        css = cfg.get("css") or (f"#{cfg['id']}" if cfg.get("id") else None)
        if css:
            try:
                await self._driver.fill(css, value)
                return True
            except Exception:
                return False
        return False

    async def _resolve_and_click_any(
        self, cfgs: list[dict], description: str = "", js_click: bool = False
    ) -> bool:
        """
        Try multiple element configs in priority order and click the first
        one that resolves. Each cfg can include "priority" to override order.
        """
        for cfg in self._ordered_cfgs(cfgs):
            cfg = {k: v for k, v in cfg.items() if k != "priority"}
            if await self._resolve_and_click(cfg, description, js_click=js_click):
                return True
        return False

    async def _resolve_and_fill_any(
        self, cfgs: list[dict], value: str, description: str = ""
    ) -> bool:
        """
        Try multiple element configs in priority order and fill the first
        one that resolves. Each cfg can include "priority" to override order.
        """
        for cfg in self._ordered_cfgs(cfgs):
            cfg = {k: v for k, v in cfg.items() if k != "priority"}
            if await self._resolve_and_fill(cfg, value, description):
                return True
        return False
