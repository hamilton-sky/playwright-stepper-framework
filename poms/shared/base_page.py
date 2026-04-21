"""
shared/base_page.py — Canonical base class for all site POMs.

Contains the resolver-aware interaction helpers that every site can use.
No site-specific logic lives here — no delays, no auth, no selectors.

Two operating modes — determined by whether resolver is injected:

  driver-only  (resolver=None)
    Interactions use CSS/id extracted directly from the Locator.

  resolver-enhanced  (resolver=ElementResolver instance)
    Interactive element finding goes through the full 10-stage cascade.
    Falls back to driver on low confidence.

Subclasses define:
  - url property
  - wait_for_ready() override (optional)
  - domain methods (search, fill_*, click_*, etc.)
"""
from __future__ import annotations
import asyncio
import logging

from poms.shared.constants import CONFIDENCE_AUTO, CONFIDENCE_WARN
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class BasePage:
    """Shared base for all site page objects across every POM package."""

    def __init__(self, driver, base_url: str, page=None, resolver=None,
                 behaviour=None):
        self._driver    = driver
        self.base_url   = base_url.rstrip("/")
        self._page      = page
        self._resolver  = resolver
        self._behaviour = behaviour

    def _sleep(self, base_ms: int):
        if self._behaviour:
            return asyncio.sleep(self._behaviour.jitter(base_ms))
        return asyncio.sleep(base_ms / 1000)

    @property
    def url(self) -> str:
        raise NotImplementedError

    async def open(self) -> None:
        await self._driver.goto(self.url, wait_until="domcontentloaded")
        await self.wait_for_ready()

    async def wait_for_ready(self) -> None:
        """Override in subclass for page-specific readiness check."""

    # ── Primary interaction method ────────────────────────────────────────────

    async def _interact(self, locator: Locator, action: str, **kwargs) -> bool:
        """
        Single dispatch for all interactive element operations.

        action: "fill"  — kwargs must contain value=str
                "click" — kwargs may contain js_click=bool

        With resolver → full 10-stage cascade via ElementResolver.
        Without resolver → driver CSS fallback via locator.css_candidates().
        Returns True on success, False if element not found or action failed.
        """
        if self._resolver and self._page:
            cfg = locator.to_cfg()
            result = await self._resolver.resolve(self._page, cfg, locator.description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        "Medium confidence %.0f%% on %s — proceeding",
                        result.confidence * 100, action,
                    )
                try:
                    el = result.locator.first
                    await el.scroll_into_view_if_needed(timeout=5_000)
                    if action == "fill":
                        if self._behaviour:
                            await asyncio.sleep(self._behaviour.jitter(50))
                        await el.fill(kwargs["value"], timeout=5_000)
                    elif action == "click":
                        if kwargs.get("js_click"):
                            await el.evaluate("el => el.click()")
                        else:
                            if self._behaviour:
                                await self._behaviour.hover_before_click(el)
                            await el.click(timeout=5_000)
                    logger.info(
                        "✓ %s via %s (%.0f%%)",
                        action, result.method, result.confidence * 100,
                    )
                    return True
                except Exception as e:
                    logger.warning("Resolver found element but %s failed: %s", action, e)
                    return False
            logger.warning(
                "Resolver could not find element for %s: %s", action, locator.description
            )
            return False

        # Driver fallback — try CSS candidates in priority order
        for css in locator.css_candidates():
            try:
                if action == "fill":
                    await self._driver.fill(css, kwargs["value"])
                    return True
                elif action == "click":
                    await self._driver.click(css)
                    return True
            except Exception:
                continue
        return False

    # ── Legacy helpers (kept for dynamic/special-case callers) ───────────────

    @staticmethod
    def _ordered_cfgs(cfgs: list[dict]) -> list[dict]:
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
        if self._resolver and self._page:
            result = await self._resolver.resolve(self._page, cfg, description)
            if result.found and result.confidence >= CONFIDENCE_WARN:
                if result.confidence < CONFIDENCE_AUTO:
                    logger.warning(
                        "Medium confidence %.0f%% on fill — proceeding",
                        result.confidence * 100,
                    )
                try:
                    await result.locator.first.scroll_into_view_if_needed(timeout=5_000)
                    if self._behaviour:
                        await asyncio.sleep(self._behaviour.jitter(50))
                    await result.locator.first.fill(value, timeout=5_000)
                    logger.info("✓ fill via %s (%.0f%%)", result.method, result.confidence * 100)
                    return True
                except Exception as e:
                    logger.warning("Resolver found element but fill failed: %s", e)
                    return False
            logger.warning("Resolver could not find element for fill: %s", cfg)
            return False

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
                        await result.locator.first.scroll_into_view_if_needed(timeout=5_000)
                        if self._behaviour:
                            await self._behaviour.hover_before_click(result.locator.first)
                        await result.locator.first.click(timeout=5_000)
                    logger.info("✓ click via %s (%.0f%%)", result.method, result.confidence * 100)
                    return True
                except Exception as e:
                    logger.warning("Resolver found element but click failed: %s", e)
                    return False
            logger.warning("Resolver could not find element for click: %s", cfg)
            return False

        css = cfg.get("css") or (f"#{cfg['id']}" if cfg.get("id") else None)
        if css:
            try:
                await self._driver.click(css)
                return True
            except Exception:
                return False
        return False

    async def _resolve_and_fill_any(
        self, cfgs: list[dict], value: str, description: str = ""
    ) -> bool:
        for cfg in self._ordered_cfgs(cfgs):
            cfg = {k: v for k, v in cfg.items() if k != "priority"}
            if await self._resolve_and_fill(cfg, value, description):
                return True
        return False

    async def _resolve_and_click_any(
        self, cfgs: list[dict], description: str = "", js_click: bool = False
    ) -> bool:
        for cfg in self._ordered_cfgs(cfgs):
            cfg = {k: v for k, v in cfg.items() if k != "priority"}
            if await self._resolve_and_click(cfg, description, js_click=js_click):
                return True
        return False

    # ── Select helper (dropdowns — no resolver needed) ────────────────────────

    async def _select_option(self, selector: str, value: str) -> None:
        if self._page:
            await self._page.select_option(selector, value)
        else:
            await self._driver.evaluate(
                f"document.querySelector('{selector}').value = '{value}';"
                f"document.querySelector('{selector}').dispatchEvent(new Event('change'));"
            )

    # ── Text extraction helpers ───────────────────────────────────────────────

    @staticmethod
    async def _get_text(element) -> str:
        if not element:
            return ""
        return (await element.inner_text()).strip()

    async def _get_all_texts(self, selector: str) -> list[str]:
        els = await self._driver.query_selector_all(selector)
        return [(await el.inner_text()).strip() for el in els]

    async def _get_text_or_none(self, selector: str) -> str | None:
        try:
            el = await self._driver.query_selector(selector)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return None
