"""
utils/book_filter.py — Pure domain functions for filtering OpenLibrary books.

No driver, no page, no Playwright. Pure functions — fully unit-testable.
SRP: knows how to filter books by year. Nothing else.
"""
from __future__ import annotations
import re


def extract_year_from_text(text: str) -> list[int]:
    """
    Extract publication years from an OpenLibrary result text snippet.
    "First published in 1965 — 120 editions" → [1965]
    Falls back to any 4-digit year in the 1000–2029 range.
    """
    m = re.search(r"First published in (\d{4})", text or "")
    if m:
        return [int(m.group(1))]
    return [int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text or "")]


def is_under_year(years: list[int], max_year: int) -> bool:
    """True if the earliest known publication year is <= max_year."""
    return bool(years) and min(years) <= max_year
