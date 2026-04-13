"""
utils/shelf.py — OpenLibrary shelf button selectors and state detection.

Pure constants and helpers — no driver, no page, no Playwright.
SRP: knows what shelf buttons look like. Nothing else.
"""
from __future__ import annotations

# CSS selectors for the shelf / "Want to Read" button
SHELF_BTN_UNACTIVATED = "button.book-progress-btn.unactivated"
SHELF_BTN_ACTIVATED   = "button.book-progress-btn.activated"
SHELF_BTN_PRIMARY     = "button.book-progress-btn.primary-action"

SHELF_LABEL_WANT    = "Want to Read"
SHELF_LABEL_ALREADY = "Already Read"

# Ordered list of CSS selectors to try when adding a book
ADD_SELECTORS: list[str] = [SHELF_BTN_UNACTIVATED, SHELF_BTN_PRIMARY]
