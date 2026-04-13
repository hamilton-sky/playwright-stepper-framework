"""
shared/base_page.py — Canonical base class for all site POMs.

Contains the resolver-aware interaction helpers that every site can use.
No site-specific logic lives here — no delays, no auth, no selectors.

Two operating modes — determined by whether resolver is injected:

  driver-only  (resolver=None)
    Interactions use CSS/id extracted directly from the cfg dict.

  resolver-enhanced  (resolver=ElementResolver instance)
    Interactive element finding goes through the full 10-stage cascade.
    Falls back to driver if resolver returns low confidence.

Subclasses define:
  - url property
  - wait_for_ready() override (optional)
  - domain methods (search, fill_*, click_*, etc.)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

CONFIDENCE_AUTO = 0.80
CONFIDENCE_WARN = 0.50


class BasePage:
    """Shared base for all site page objects across every POM package."""

    def __init__(self, driver, base_url: str, page=None, resolver=None):
        self._driver   = driver
        self.base_url  = base_url.rstrip("/")
        self._page     = page      # Playwright Page — for resolver
        self._resolver = resolver  # ElementResolver — 10-stage cascade (optional)

    @property
    def url(self) -> str:
        raise NotImplementedError

    async def open(self) -> None:
        await self._driver.goto(self.url, wait_until="domcontentloaded")
        await self.wait_for_ready()

    async def wait_for_ready(self) -> None:
        """Override in subclass for page-specific readiness check."""

    # ── Priority ordering ─────────────────────────────────────────────────────

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

    # ── Single-cfg helpers ────────────────────────────────────────────────────

    async def _resolve_and_fill(
        self, cfg: dict, value: str, description: str = ""
    ) -> bool:
        """
        Find an element and fill it.
        With resolver → full 10-stage cascade.
        Without resolver → driver CSS/id fallback.
        Returns True on success, False if element not found.
        """
        if self._resolver and self._page:
            result = await self._resolver.resolve(self._page, cfg, description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        "Medium confidence %.0f%% on fill — proceeding",
                        result.confidence * 100,
                    )
                try:
                    await result.locator.scroll_into_view_if_needed(timeout=5_000)
                    await result.locator.first.fill(value, timeout=5_000)
                    logger.info("✓ fill via %s (%.0f%%)", result.method, result.confidence * 100)
                    return True
                except Exception as e:
                    logger.warning("Resolver found element but fill failed: %s", e)
                    return False
            logger.warning("Resolver could not find element for fill: %s", cfg)
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

    async def _resolve_and_click(
        self, cfg: dict, description: str = "", js_click: bool = False
    ) -> bool:
        """
        Find an element and click it.
        With resolver → full 10-stage cascade.
        Without resolver → driver CSS/id fallback.
        Returns True on success, False if element not found.
        """
        if self._resolver and self._page:
            result = await self._resolver.resolve(self._page, cfg, description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        "Medium confidence %.0f%% on click — proceeding",
                        result.confidence * 100,
                    )
                try:
                    if js_click:
                        await result.locator.first.evaluate("el => el.click()")
                    else:
                        await result.locator.scroll_into_view_if_needed(timeout=5_000)
                        await result.locator.click(timeout=5_000)
                    logger.info("✓ click via %s (%.0f%%)", result.method, result.confidence * 100)
                    return True
                except Exception as e:
                    logger.warning("Resolver found element but click failed: %s", e)
                    return False
            logger.warning("Resolver could not find element for click: %s", cfg)
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

    # ── Multi-cfg (priority list) helpers ────────────────────────────────────

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
