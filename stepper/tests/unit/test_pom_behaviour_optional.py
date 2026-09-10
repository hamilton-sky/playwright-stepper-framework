"""
POMs must work with behaviour=None.

pom-layer.md states it, SharedBasePage honours it via _sleep/_hover, and
examples/plain_pom relies on it — driver-only mode constructs every POM without
a behaviour.

BookDetailPage used to dereference self._behaviour eight times unguarded. It did
not crash, which is what made it hard to see: every call sat inside a
`try/except Exception` that swallowed the AttributeError and returned False, so
"the code has a None bug" was indistinguishable from "the selector did not
match". Driver-only mode simply could not shelf a book.

These tests fail if a POM reaches for self._behaviour directly again.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POMS = _REPO_ROOT / "poms"


# ── The static rule ───────────────────────────────────────────────────────────

def _unguarded_behaviour_uses(path: Path) -> list[str]:
    """
    Attribute access on self._behaviour that is not inside an `if self._behaviour`.

    SharedBasePage is exempt: it is where the guards live.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # `if self._behaviour:` — the guard SharedBasePage uses
        if (isinstance(test, ast.Attribute) and test.attr == "_behaviour"
                and isinstance(test.value, ast.Name) and test.value.id == "self"):
            for child in ast.walk(node):
                guarded.add(id(child))

    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "_behaviour"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and id(node) not in guarded):
            found.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} self._behaviour.{node.attr}")
    return found


def _pom_files() -> list[Path]:
    return sorted(p for p in _POMS.rglob("*.py")
                  if p.name != "base_page.py" or p.parent.name != "shared")


def test_pom_files_were_found():
    assert len(_pom_files()) > 10, "POM discovery broke; the rule below would pass vacuously"


def test_no_pom_touches_behaviour_unguarded():
    offenders = [use for path in _pom_files() for use in _unguarded_behaviour_uses(path)]

    assert not offenders, (
        "These reach for self._behaviour without a guard. In driver-only mode "
        "behaviour is None, and the AttributeError is usually swallowed by a "
        "surrounding try/except — a silent failure, not a crash.\n"
        "Use the SharedBasePage helpers instead: self._sleep(ms), self._hover(el).\n  "
        + "\n  ".join(offenders)
    )


# ── The behaviour it protects ─────────────────────────────────────────────────

def _detail_page(behaviour):
    from poms.openLibrary.pages.book_detail_page import BookDetailPage

    driver = MagicMock()
    element = MagicMock()
    element.click = AsyncMock()
    element.inner_text = AsyncMock(return_value="Want to Read")
    driver.wait_for_selector  = AsyncMock(return_value=element)
    driver.query_selector     = AsyncMock(return_value=element)
    driver.query_selector_all = AsyncMock(return_value=[element])

    page = BookDetailPage(driver, "https://openlibrary.org",
                          book_url="/works/OL1W", behaviour=behaviour)
    page._shelf_label = "Want to Read"
    return page


@pytest.mark.parametrize("with_behaviour", [True, False], ids=["with_behaviour", "driver_only"])
def test_shelf_dropdown_works_in_both_modes(with_behaviour):
    """Regression: driver-only mode returned False here while the other returned True."""
    from engine.browser.human_behaviour import HumanBehaviour

    page = _detail_page(HumanBehaviour() if with_behaviour else None)

    assert asyncio.run(page._step_dropdown_shelf()) is True


def test_wait_for_ready_does_not_need_a_behaviour():
    page = _detail_page(None)

    asyncio.run(page.wait_for_ready())   # must not raise


def test_the_shared_helpers_tolerate_no_behaviour():
    from poms.shared.base_page import BasePage

    page = BasePage(MagicMock(), "https://example.test", behaviour=None)

    asyncio.run(page._sleep(1))
    asyncio.run(page._hover(MagicMock()))   # no-op, must not raise
