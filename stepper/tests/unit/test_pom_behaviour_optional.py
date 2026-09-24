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
    from stepper.engine.browser.human_behaviour import HumanBehaviour

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


# ── Every POM must be constructible the way the glue builds it ────────────────
#
# The rule above says a POM must *work* with behaviour=None. This one says it
# must accept the argument at all.
#
# `_build_pom` passes page=, resolver= and behaviour= as keywords to every POM
# in the tree. phpTravels' HotelDetailPage — alone of its four — declared
# `(self, driver, base_url, hotel_slug=None, page=None, resolver=None)`, so
# every attempt to build it raised
#
#     TypeError: __init__() got an unexpected keyword argument 'behaviour'
#
# which the glue's `except Exception` reported as an ordinary failed step.
# pt_book_hotel, the last step of that site's only workflow, had never run.
# Nothing caught it because nothing constructed the class: the signature is
# wrong in a way only a call reveals, and no call existed.

def _pom_classes():
    """Every concrete POM class, found by importing each POM module."""
    import importlib
    import inspect

    from poms.shared.base_page import BasePage as SharedBasePage

    found = []
    for path in _pom_files():
        rel = path.relative_to(_REPO_ROOT).with_suffix("")
        module = importlib.import_module(".".join(rel.parts))
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, SharedBasePage) and cls is not SharedBasePage
                    and cls.__module__ == module.__name__
                    and not cls.__name__ == "BasePage"):
                found.append(cls)
    return found


def test_pom_class_discovery_did_not_break():
    assert len(_pom_classes()) > 25, "the rule below would pass vacuously"


def _required_positionals(pom_cls) -> list:
    """
    Stand-ins for whatever else the constructor demands — a book url, an item
    id, a hotel slug. Filling them from the signature is what keeps this rule
    honest: an earlier version passed only driver and base_url and reported
    BookDetailPage as broken when it was merely asked for less than it needs.
    """
    import inspect

    params = list(inspect.signature(pom_cls.__init__).parameters.values())[1:]
    args = []
    for prm in params:
        if prm.name in {"page", "resolver", "behaviour"}:
            continue
        if prm.kind in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD):
            continue
        if prm.default is not prm.empty:
            break
        args.append("https://example.test" if prm.name == "base_url" else MagicMock())
    return args


@pytest.mark.parametrize(
    "pom_cls", _pom_classes(),
    ids=lambda c: f"{c.__module__.split('.')[1]}.{c.__name__}",
)
def test_every_pom_takes_and_keeps_the_injected_behaviour(pom_cls):
    """
    Built exactly as GlueAction._build_pom builds it, and then checked that the
    behaviour arrived. Two failure modes, one rule:

      raises TypeError  — the constructor has no behaviour parameter, so the
                          action cannot build the POM at all. phpTravels'
                          HotelDetailPage was this, and pt_book_hotel had
                          therefore never run.
      _behaviour is None — the constructor accepts it and drops it on the way
                          to super(), which is a silently un-humanised POM:
                          no jitter, no hover dwell, and nothing says so.
    """
    sentinel = object()
    try:
        pom = pom_cls(*_required_positionals(pom_cls),
                      page=MagicMock(), resolver=None, behaviour=sentinel)
    except TypeError as e:
        pytest.fail(
            f"{pom_cls.__module__}.{pom_cls.__name__} cannot be built the way "
            f"_build_pom builds every POM: {e}\n"
            f"Its __init__ must accept page=, resolver= and behaviour= as "
            f"keywords and pass them to super()."
        )

    assert pom._behaviour is sentinel, (
        f"{pom_cls.__module__}.{pom_cls.__name__} accepted behaviour= and did "
        f"not pass it to super() — the POM is silently un-humanised"
    )


# ── Every click is humanised, including the ones _interact never sees ─────────
#
# `_interact` hovers before it clicks when a behaviour is injected. A POM that
# reaches past it — to pick the first of several rows, to follow a pagination
# link — gets no hover for free, and skipping it leaves that one click
# un-humanised on a live, often bot-protected site. Silently, too: a behaviour
# object that is held but never used looks exactly like one that is working,
# which is why the constructor rule above cannot catch this.
#
# Found by Codex on PR #33, on a click this session had just introduced. The
# audit that followed found nine more across four sites. openLibrary's
# book_detail_page already did it correctly and is what the fix copied.


def _handle_clicks_without_a_hover(path: Path) -> list[str]:
    """
    `await <handle>.click()` whose preceding statement is not `await self._hover(…)`.

    Clicks through `self` are exempt: `self._driver.click(css)` goes through the
    adapter, and `self._interact(...)` does its own hovering.
    """
    def root(node):
        while True:
            if isinstance(node, ast.Attribute):
                node = node.value
            elif isinstance(node, ast.Subscript):
                node = node.value
            elif isinstance(node, ast.Call):
                node = node.func
            else:
                return node

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for parent in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(parent, attr, None)
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await)):
                    continue
                call = stmt.value.value
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "click"):
                    continue
                base = root(call.func.value)
                if isinstance(base, ast.Name) and base.id == "self":
                    continue
                prev = block[i - 1] if i else None
                hovered = (
                    isinstance(prev, ast.Expr) and isinstance(prev.value, ast.Await)
                    and isinstance(prev.value.value, ast.Call)
                    and isinstance(prev.value.value.func, ast.Attribute)
                    and prev.value.value.func.attr == "_hover"
                )
                if not hovered:
                    found.append(
                        f"{path.relative_to(_REPO_ROOT)}:{stmt.lineno}  "
                        f"{ast.unparse(call)[:50]}"
                    )
    return found


def test_no_pom_clicks_a_handle_without_hovering_first():
    exempt = {"base_page.py", "driver.py"}
    offenders = [
        hit
        for path in _pom_files()
        if not (path.parent.name == "shared" and path.name in exempt)
        for hit in _handle_clicks_without_a_hover(path)
    ]

    assert not offenders, (
        "These click an element handle directly, so they miss the hover-and-dwell "
        "that _interact applies to every other click — one un-humanised click on "
        "a live site, and nothing says so.\n"
        "Put `await self._hover(el)` immediately before the click; it applies the "
        "behaviour when one is injected and is a no-op when it is None.\n  "
        + "\n  ".join(offenders)
    )
