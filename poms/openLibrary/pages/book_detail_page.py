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
        ]
        # Dropdown widget selectors (revealed by clicking the caret)
        SHELF_DROPDOWN_CARET  = "a.generic-dropper__dropclick"
        SHELF_DROPDOWN_BTNS   = ".read-statuses button.nostyle-btn"

    def __init__(self, driver, base_url: str, book_url: str,
                 delays=None, page=None, resolver=None):
        super().__init__(driver, base_url, delays, page, resolver)
        self._url         = book_url
        self._shelf_label: str | None = None  # set by add_to_reading_list before steps run

        # OCP: resolution order is data-driven — add a step by appending here.
        # add_to_reading_list() iterates this list; it never needs editing.
        self._add_steps: list[Callable[[], Awaitable[bool]]] = [
            self._step_already_shelved,   # 1. idempotent guard
            self._step_resolver_role,     # 2. ARIA role + label ("Want to Read" → 95% confidence)
            self._step_dropdown_shelf,    # 3. open caret dropdown → click target shelf
            self._step_resolver_css,      # 4. resolver cascade with CSS (fallback)
            self._step_driver_fallback,   # 5. direct driver CSS (last resort)
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

        Only attempted for the primary shelf label (SHELF_LABEL_WANT).
        Non-primary shelves ("Already Read", "Currently Reading") are never
        top-level ARIA buttons — they live inside the dropdown revealed by
        _step_dropdown_shelf. Trying the resolver for them produces expected
        warnings and wastes ~1s, so we skip straight to the dropdown step.
        """
        if self._shelf_label != SHELF_LABEL_WANT:
            return False
        clicked = await self._resolve_and_click(
            {"role": "button", "name": self._shelf_label},
            description=f"shelf button labelled '{self._shelf_label}'",
            js_click=True,
        )
        if clicked:
            logger.info(f"✓ Added to shelf via role resolver: '{self._shelf_label}'")
        return clicked

    async def _step_dropdown_shelf(self) -> bool:
        """
        Step 3: Open the shelf dropdown via the caret and click the target shelf.

        Non-primary shelves ("Already Read", "Currently Reading") are only
        accessible inside a hidden dropdown — they are never top-level ARIA
        buttons, so the role resolver can't find them without opening it first.

        DOM structure (verified April 2026):
          a.generic-dropper__dropclick  → caret that reveals the dropdown
          .read-statuses button.nostyle-btn  → one button per shelf option
        """
        try:
            caret = await self._driver.wait_for_selector(
                self.Locators.SHELF_DROPDOWN_CARET, timeout=3_000
            )
            if not caret:
                return False
            await caret.click()
            await asyncio.sleep(0.3)

            buttons = await self._driver.query_selector_all(
                self.Locators.SHELF_DROPDOWN_BTNS
            )
            for btn in buttons:
                text = (await btn.inner_text()).strip()
                if text == self._shelf_label:
                    await btn.click()
                    logger.info("✓ Added to shelf via dropdown: '%s'", self._shelf_label)
                    return True

            logger.debug("_step_dropdown_shelf: '%s' not found in dropdown buttons", self._shelf_label)
            return False
        except Exception as e:
            logger.debug("_step_dropdown_shelf failed: %s", e)
            return False

    async def _step_resolver_css(self) -> bool:
        """Step 4: Resolver cascade with CSS selectors from Locators."""
        clicked = await self._resolve_and_click_any(
            self.Locators.ADD_PRIORITY_CFGS,
            description="unactivated shelf button",
        )
        if clicked:
            logger.info("✓ Added to shelf via CSS resolver (priority list)")
        return clicked

    async def _step_driver_fallback(self) -> bool:
        """Step 5: Direct driver CSS — last resort, no resolver."""
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

        Returns True if removed, False if the book was not on any shelf.

        OL has two removal behaviours depending on widget state:
          A. Click activated button → dropdown appears → click "Remove From Shelf"
          B. Click activated button → OL toggles removal directly (widget closes)

        We detect success by checking activated state before and after the click,
        so both behaviours return the correct value.
        """
        # Guard: if not on any shelf, nothing to do
        activated_before = await self._driver.query_selector(
            self.Locators.SHELF_BTN_ACTIVATED
        )
        if not activated_before:
            return False

        # 2. Click the main button to trigger removal/dropdown
        try:
            el = await self._driver.wait_for_selector(
                self.Locators.SHELF_BTN_BASE, timeout=5_000
            )
            await el.click()
        except Exception:
            return False

        # 3. THE FIX: Check for the dropdown "Remove" button with a SHORT timeout
        try:
            # If Path A (dropdown) exists, this finds it in 1s.
            # If Path B (toggle) happened, this fails in 1s instead of 30s!
            remove_el = await self._driver.wait_for_selector(
                self.Locators.REMOVE_FROM_LIST, 
                timeout=1000 
            )
            if remove_el:
                await remove_el.click()
                logger.info("✓ Removed via dropdown Path A")
                return True
        except Exception:
            # If we timeout here, it just means the dropdown didn't appear.
            # We move on to check if the toggle worked instead.
            pass

        # 4. Final check for Path B (Direct Toggle)
        await asyncio.sleep(0.5) 
        still_activated = await self._driver.query_selector(
            self.Locators.SHELF_BTN_ACTIVATED
        )
        if not still_activated:
            logger.info("✓ Removed via toggle Path B")
            return True

        return False
