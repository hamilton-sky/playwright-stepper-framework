"""
utils/selector.py — Data-driven selector fallback chain.

SRP: knows how to try a list of CSS selectors in order.
OCP: extend by adding selectors to the list — zero edits to this class.

No Playwright imports — depends only on IBrowserDriver interface (DIP).
"""
from __future__ import annotations
import logging

from shared_poms.interfaces import IBrowserDriver

logger = logging.getLogger(__name__)


class SelectorFallbackChain:
    """
    Try a list of CSS selectors in order for fill or click.

    Usage:
        chain = SelectorFallbackChain(driver, ["#q", "input[name='q']"])
        filled = await chain.fill("Dune")
        clicked = await chain.click()

    OCP: adding a new fallback = one extra string in the list passed at
    construction. Zero edits to this class.
    """

    def __init__(self, driver: IBrowserDriver, selectors: list[str]) -> None:
        self._driver    = driver
        self._selectors = selectors

    async def fill(self, value: str) -> bool:
        """Try each selector for a fill operation. Returns True on first success."""
        for sel in self._selectors:
            try:
                await self._driver.fill(sel, value)
                logger.debug(f"SelectorFallbackChain.fill: matched {sel!r}")
                return True
            except Exception:
                continue
        logger.warning(
            f"SelectorFallbackChain.fill: no selector matched from {self._selectors}"
        )
        return False

    async def click(self) -> bool:
        """Try each selector for a click operation. Returns True on first success."""
        for sel in self._selectors:
            try:
                await self._driver.click(sel)
                logger.debug(f"SelectorFallbackChain.click: matched {sel!r}")
                return True
            except Exception:
                continue
        logger.warning(
            f"SelectorFallbackChain.click: no selector matched from {self._selectors}"
        )
        return False
