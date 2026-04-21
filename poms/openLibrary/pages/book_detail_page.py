"""
pages/book_detail_page.py — POM for OpenLibrary book detail page.

Responsibility: orchestrate the book detail page flow.
  open → detect shelf state → add to reading list

OCP — add_to_reading_list resolution order:
  Each resolution strategy is a private async method (_step_*).
  To add a new strategy: add a method + append it to self._add_steps in __init__.
  Zero edits to add_to_reading_list() or any other step.
"""
from __future__ import annotations
import asyncio
import logging
import random
from typing import Callable, Awaitable

from poms.openLibrary.pages.base_page import BasePage
from poms.openLibrary.utils.shelf import SHELF_LABEL_WANT, SHELF_LABEL_ALREADY
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class BookDetailPage(BasePage):

    class Locators:
        """All selectors for the book detail page. Single source of truth."""

        # ── Read-only state checks ────────────────────────────────────────────
        SHELF_BTN_BASE        = "button.book-progress-btn"
        SHELF_BTN_ACTIVATED   = "button.book-progress-btn.activated"
        SHELF_BTN_UNACTIVATED = "button.book-progress-btn.unactivated"
        SHELF_BTN_PRIMARY     = "button.book-progress-btn.primary-action"
        REMOVE_FROM_LIST      = "button.remove-from-list"

        # CSS list used by driver fallback step (plain strings, read-only path)
        ADD_SELECTORS = [SHELF_BTN_UNACTIVATED, SHELF_BTN_PRIMARY, SHELF_BTN_BASE, SHELF_BTN_ACTIVATED]

        # ── Interactive ───────────────────────────────────────────────────────
        # Used by _step_resolver_css — primary + CSS fallbacks cover class variants
        SHELF_ADD = Locator(
            text="Want to Read",
            css="button.book-progress-btn.unactivated",
            css_fallbacks=["button.book-progress-btn.primary-action"],
            description="unactivated shelf button",
        )

        # Dropdown widget selectors (read-only — caret revealed via driver)
        SHELF_DROPDOWN_CARET = "a.generic-dropper__dropclick"
        SHELF_DROPDOWN_BTNS  = ".read-statuses button.nostyle-btn"

    def __init__(self, driver, base_url: str, book_url: str,
                 delays=None, page=None, resolver=None, **kwargs):
        super().__init__(driver, base_url, delays, page, resolver, **kwargs)
        self._url         = book_url
        self._shelf_label: str | None = None

        self._add_steps: list[Callable[[], Awaitable[bool]]] = [
            self._step_already_shelved,
            self._step_resolver_role,
            self._step_dropdown_shelf,
            self._step_resolver_css,
            self._step_driver_fallback,
        ]

    @property
    def url(self) -> str:
        return self._url

    async def wait_for_ready(self) -> None:
        logger.info("Waiting for shelf button on %s", self._url)
        try:
            await self._driver.wait_for_selector(
                self.Locators.SHELF_BTN_BASE, timeout=10_000
            )
            await asyncio.sleep(self._behaviour.jitter(1000))
            logger.info("Shelf button ready")
        except Exception:
            logger.warning("Shelf button not visible on %s — continuing", self._url)

    async def add_to_reading_list(self, label: str | None = None) -> str | None:
        self._shelf_label = label or random.choice([SHELF_LABEL_WANT, SHELF_LABEL_ALREADY])
        logger.info("Adding to shelf: '%s'  url=%s", self._shelf_label, self._url)

        for step in self._add_steps:
            if await step():
                return self._shelf_label

        logger.warning(f"First pass failed on {self._url} — reloading and retrying")
        await self.open()
        for step in self._add_steps:
            if await step():
                return self._shelf_label

        logger.warning(f"⚠ Could not find shelf button on {self._url}")
        return None

    # ── Resolution steps ──────────────────────────────────────────────────────

    async def _step_already_shelved(self) -> bool:
        try:
            if await self._driver.query_selector(self.Locators.SHELF_BTN_ACTIVATED):
                logger.info("✓ Book already on shelf (activated button found)")
                return True
        except Exception:
            pass
        return False

    async def _step_resolver_role(self) -> bool:
        """
        Resolver cascade using ARIA role + label set at runtime.
        Only attempted for the primary shelf label (SHELF_LABEL_WANT) —
        non-primary shelves live inside the dropdown.
        """
        if self._shelf_label != SHELF_LABEL_WANT:
            return False
        locator = Locator(
            role="button", name=self._shelf_label,
            description=f"shelf button labelled '{self._shelf_label}'",
        )
        clicked = await self._interact(locator, "click", js_click=True)
        if clicked:
            logger.info(f"✓ Added to shelf via role resolver: '{self._shelf_label}'")
        return clicked

    async def _step_dropdown_shelf(self) -> bool:
        """
        Open the shelf dropdown via the caret and click the target shelf.
        Non-primary shelves are only accessible inside this hidden dropdown.
        """
        try:
            caret = await self._driver.wait_for_selector(
                self.Locators.SHELF_DROPDOWN_CARET, timeout=3_000
            )
            if not caret:
                return False

            await self._behaviour.hover_before_click(caret)
            await caret.click()
            await asyncio.sleep(self._behaviour.jitter(300))

            buttons = await self._driver.query_selector_all(
                self.Locators.SHELF_DROPDOWN_BTNS
            )
            for btn in buttons:
                text = (await btn.inner_text()).strip()
                if text == self._shelf_label:
                    await self._behaviour.hover_before_click(btn)
                    await btn.click()
                    logger.info("✓ Added to shelf via dropdown: '%s'", self._shelf_label)
                    return True

            logger.debug("_step_dropdown_shelf: '%s' not found in dropdown buttons", self._shelf_label)
            return False
        except Exception as e:
            logger.debug("_step_dropdown_shelf failed: %s", e)
            return False

    async def _step_resolver_css(self) -> bool:
        """Resolver cascade with CSS/text Locator."""
        clicked = await self._interact(self.Locators.SHELF_ADD, "click")
        if clicked:
            logger.info("✓ Added to shelf via CSS resolver")
        return clicked

    async def _step_driver_fallback(self) -> bool:
        """Direct driver CSS — last resort, no resolver."""
        selectors = [*self.Locators.ADD_SELECTORS]
        for selector in selectors:
            try:
                el = await self._driver.wait_for_selector(selector, timeout=5_000)
                if el:
                    await self._behaviour.hover_before_click(el)
                    await el.click()
                    logger.info(f"✓ Added to shelf via driver fallback: {selector}")
                    return True
            except Exception as e:
                logger.debug("_step_driver_fallback: selector %r failed: %s", selector, e)
                continue
        return False

    async def remove_from_shelf(self) -> bool:
        activated_before = await self._driver.query_selector(
            self.Locators.SHELF_BTN_ACTIVATED
        )
        if not activated_before:
            return False

        try:
            el = await self._driver.wait_for_selector(
                self.Locators.SHELF_BTN_BASE, timeout=5_000
            )
            await self._behaviour.hover_before_click(el)
            await el.click()
        except Exception:
            return False

        try:
            remove_el = await self._driver.wait_for_selector(
                self.Locators.REMOVE_FROM_LIST, timeout=1000
            )
            if remove_el:
                await self._behaviour.hover_before_click(remove_el)
                await remove_el.click()
                logger.info("✓ Removed via dropdown Path A")
                return True
        except Exception:
            pass

        await asyncio.sleep(self._behaviour.jitter(500))
        still_activated = await self._driver.query_selector(
            self.Locators.SHELF_BTN_ACTIVATED
        )
        if not still_activated:
            logger.info("✓ Removed via toggle Path B")
            return True

        return False
