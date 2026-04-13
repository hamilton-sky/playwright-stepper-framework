"""
pages/book_detail_page.py — POM for OpenLibrary book detail page.

Responsibility: orchestrate the book detail page flow.
  open → detect shelf state → add to reading list

Uses:
  - openlibrary_exam.utils.shelf  (button selectors — pure constants)
  - openlibrary_exam.pages.base_page (BasePage)

No src/ imports. No framework imports.
Resolver is accepted as optional — injected by Stepper glue at runtime.

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

logger = logging.getLogger(__name__)


class BookDetailPage(BasePage):
    """
    POM for the OpenLibrary book detail page.

    All CSS selectors live in the inner Locators class — single source of truth.
    Resolution order for add_to_reading_list is data-driven via self._add_steps.
    """

    class Locators:
        """CSS selectors owned by BookDetailPage. Never duplicate elsewhere."""
        SHELF_BTN_BASE        = "button.book-progress-btn"
        SHELF_BTN_ACTIVATED   = "button.book-progress-btn.activated"
        SHELF_BTN_UNACTIVATED = "button.book-progress-btn.unactivated"
        SHELF_BTN_PRIMARY     = "button.book-progress-btn.primary-action"
        REMOVE_FROM_LIST      = "button.remove-from-list"
        # Ordered list used by CSS-based fallback steps
        ADD_SELECTORS         = [SHELF_BTN_UNACTIVATED, SHELF_BTN_PRIMARY]
        # Priority-configured resolver list (lower = first)
        # role+name is handled dynamically in _step_resolver_role (shelf label is runtime).
        # text entries here act as static fallbacks when CSS classes change.
        ADD_PRIORITY_CFGS     = [
            {"css":  SHELF_BTN_UNACTIVATED, "priority": 10},
            {"css":  SHELF_BTN_PRIMARY,     "priority": 20},
            {"text": "Want to Read",        "priority": 30},
            {"text": "Already Read",        "priority": 40},
        ]

    def __init__(self, driver, base_url: str, book_url: str,
                 delays=None, page=None, resolver=None):
        super().__init__(driver, base_url, delays, page, resolver)
        self._url         = book_url
        self._shelf_label: str | None = None  # set by add_to_reading_list before steps run

        # OCP: resolution order is data-driven — add a step by appending here.
        # add_to_reading_list() iterates this list; it never needs editing.
        self._add_steps: list[Callable[[], Awaitable[bool]]] = [
            self._step_already_shelved,   # 1. idempotent guard
            self._step_resolver_role,     # 2. ARIA role + label (most resilient)
            self._step_resolver_css,      # 3. resolver cascade with CSS
            self._step_driver_fallback,   # 4. direct driver CSS (last resort)
        ]

    @property
    def url(self) -> str:
        return self._url

    async def wait_for_ready(self) -> None:
        """Wait for the shelf button to appear before attempting interactions."""
        logger.info("Waiting for shelf button on %s", self._url)
        try:
            await self._driver.wait_for_selector(
                self.Locators.SHELF_BTN_BASE, timeout=10_000
            )
            logger.info("Shelf button ready")
        except Exception:
            logger.warning("Shelf button not visible on %s — continuing", self._url)

    async def add_to_reading_list(self, label: str | None = None) -> str | None:
        """
        Click the shelf button to add the book to the reading list.

        label: which shelf to target ("Want to Read" / "Already Read").
               Pass None to pick randomly (exam spec default).
               Pass a specific value in tests for deterministic assertions.

        Resolution order is defined in self._add_steps (OCP — extend by appending,
        never by editing this method).

        Returns the shelf label string if added or already shelved, None if nothing
        worked after retry.
        """
        self._shelf_label = label or random.choice([SHELF_LABEL_WANT, SHELF_LABEL_ALREADY])
        logger.info("Adding to shelf: '%s'  url=%s", self._shelf_label, self._url)

        for step in self._add_steps:
            if await step():
                return self._shelf_label

        # First pass failed — reload the page and try once more.
        # Handles timing issues where the shelf widget loads late.
        logger.warning(f"First pass failed on {self._url} — reloading and retrying")
        await self.open()
        for step in self._add_steps:
            if await step():
                return self._shelf_label

        logger.warning(f"⚠ Could not find shelf button on {self._url}")
        return None

    # ── Resolution steps (private) ────────────────────────────────────────────

    async def _step_already_shelved(self) -> bool:
        """Step 1: Return True immediately if book is already on a shelf (idempotent)."""
        try:
            if await self._driver.query_selector(self.Locators.SHELF_BTN_ACTIVATED):
                logger.info("✓ Book already on shelf (activated button found)")
                return True
        except Exception:
            pass
        return False

    async def _step_resolver_role(self) -> bool:
        """
        Step 2: Resolver cascade using ARIA role + label set by add_to_reading_list.
        Most resilient — survives CSS class renames.
        """
        clicked = await self._resolve_and_click(
            {"role": "button", "name": self._shelf_label},
            description=f"shelf button labelled '{self._shelf_label}'",
            js_click=True,
        )
        if clicked:
            logger.info(f"✓ Added to shelf via role resolver: '{self._shelf_label}'")
        return clicked

    async def _step_resolver_css(self) -> bool:
        """Step 3: Resolver cascade with CSS selectors from Locators."""
        clicked = await self._resolve_and_click_any(
            self.Locators.ADD_PRIORITY_CFGS,
            description="unactivated shelf button",
        )
        if clicked:
            logger.info("✓ Added to shelf via CSS resolver (priority list)")
        return clicked

    async def _step_driver_fallback(self) -> bool:
        """Step 4: Direct driver CSS — last resort, no resolver."""
        # Include base selector as final fallback for buttons without a known class state.
        selectors = [*self.Locators.ADD_SELECTORS, self.Locators.SHELF_BTN_BASE]
        for selector in selectors:
            try:
                el = await self._driver.wait_for_selector(selector, timeout=5_000)
                if el:
                    await el.click()
                    logger.info(f"✓ Added to shelf via driver fallback: {selector}")
                    return True
            except Exception as e:
                logger.debug("_step_driver_fallback: selector %r failed: %s", selector, e)
                continue
        return False

    async def remove_from_shelf(self) -> bool:
        """
        Remove this book from whatever shelf it is on.

        Uses direct wait_for_selector + click with short timeouts to avoid
        the 60s hang that occurs when the remove button never appears.
        The 0.5s sleep gives the dropdown time to render after the first click.
        Returns True if removed, False if not on any shelf.
        """
        # Step 1: click the shelf button to open the dropdown
        try:
            el = await self._driver.wait_for_selector(
                self.Locators.SHELF_BTN_BASE, timeout=5_000
            )
            if not el:
                logger.debug("remove_from_shelf: no shelf button on %s", self._url)
                return False
            await el.click()
        except Exception as e:
            logger.debug("remove_from_shelf: shelf button click failed on %s: %s", self._url, e)
            return False

        # Step 2: wait for the dropdown to render before looking for the remove button
        await asyncio.sleep(0.5)

        # Step 3: click the remove button
        try:
            remove_el = await self._driver.wait_for_selector(
                self.Locators.REMOVE_FROM_LIST, timeout=5_000
            )
            if remove_el:
                await remove_el.click()
                logger.info("✓ Removed from shelf: %s", self._url)
                return True
        except Exception as e:
            logger.debug("remove_from_shelf: remove button not found on %s: %s", self._url, e)

        return False
