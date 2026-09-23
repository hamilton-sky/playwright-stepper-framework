"""
A `ti` action that did not act must not report "passed".

This rule is not speculative — it is written from a flow that lied. `ti` was
generated from a crawl and eight workflows came with it; six had never run,
because this environment's egress policy denies the-internet.herokuapp.com.
Run against local fixtures, seven worked and one did not:

    Resolver found element but click failed: scroll_into_view_if_needed: Timeout
    ti_hover_user ✓ — hovered avatar and clicked profile link
    ✓ Step 1 → passed

Two defects stacked, and the second hid the first:

  1. HoversPage used `.figure:nth-child(1) img`, which reads as "the first
     .figure" and is not — :nth-child(1) means "is the first child of its
     parent AND is a .figure", and the-internet puts an <h3> and a <br> ahead
     of them. 0 matches, so the hover never fired and the CSS-hidden caption
     never appeared.
  2. `hover_user_avatar_1` returned None on a missing element and the glue
     returned "passed" unconditionally, so a flow that navigated nowhere
     reported 1/1 green.

Same family as Pathly's — see test_pathly_failure_propagation.py. The rules
below are the `ti` half.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stepper.engine.interfaces import ExecutionContext, StepConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TI_POMS = _REPO_ROOT / "poms" / "ti" / "pages"


# ── The static rule ───────────────────────────────────────────────────────────

def _discarded_interacts(path: Path) -> list[str]:
    """`await self._interact(...)` as a bare statement, its result unread."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.relative_to(_REPO_ROOT)}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Attribute)
        and node.value.value.func.attr == "_interact"
    ]


def _ti_pom_files() -> list[Path]:
    return sorted(p for p in _TI_POMS.glob("*.py")
                  if p.name not in {"__init__.py", "base_page.py"})


def test_ti_pom_discovery_did_not_break():
    assert len(_ti_pom_files()) == 8, "the rule below would pass vacuously"


def test_no_ti_pom_discards_an_interact_result():
    offenders = [hit for path in _ti_pom_files() for hit in _discarded_interacts(path)]

    assert not offenders, (
        "_interact returns False rather than raising when the element is not "
        "there. Discarding it is what let a 0-match selector report success.\n"
        "Return it — `return await self._interact(...)` — and let the glue "
        "decide.\n  " + "\n  ".join(offenders)
    )


# ── The selector that started it ──────────────────────────────────────────────

def test_the_hovers_avatar_selector_is_nth_of_type():
    """
    A regression pin on one character of CSS, because the difference is
    invisible on inspection and total at runtime.

    :nth-child(1)   → "first child of its parent, and a .figure"  → 0 matches
    :nth-of-type(1) → "first div among its siblings, and a .figure" → 1 match
    """
    from poms.ti.pages.hovers_page import HoversPage

    css = HoversPage.Locators.USER_AVATAR_1.css

    assert "nth-child" not in css, (
        "the-internet's .figure elements are preceded by <h3> and <br>, so they "
        "are children 3, 4 and 5 — :nth-child(1) matches nothing"
    )
    assert "nth-of-type(1)" in css


# ── The behavioural rule ──────────────────────────────────────────────────────

def _actions():
    """Every ti action that drives an element, with the extra it needs."""
    from stepper.sites.ti.pages.checkboxes_action import TiCheckboxesPage
    from stepper.sites.ti.pages.hovers_action import TiHoversPage
    from stepper.sites.ti.pages.js_alerts_action import TiJsAlertsPage
    from stepper.sites.ti.pages.login_action import TiLoginPage
    from stepper.sites.ti.pages.logout_action import TiLogoutPage

    return [
        (TiCheckboxesPage.TiToggleCheckboxesAction(), {}),
        (TiJsAlertsPage.TiHandleAlertsAction(), {}),
        (TiHoversPage.TiHoverUserAction(), {}),
        (TiLoginPage.TiLoginAction(), {"username": "u", "password": "p"}),
        (TiLogoutPage.TiLogoutAction(), {}),
    ]


def _ids():
    return [a.action_name for a, _ in _actions()]


@pytest.fixture
def every_lookup_misses(monkeypatch):
    """
    The state the broken selector produced: nothing on the page resolves.
    `_interact` answers False the way it does for a 0-match cfg; the driver
    answers None the way `query_selector` does. No browser, no resolver.
    """
    from poms.shared.base_page import BasePage

    async def _false(self, locator, action, **kwargs):
        return False

    async def _noop(self, *a, **k):
        return None

    monkeypatch.setattr(BasePage, "_interact", _false)
    monkeypatch.setattr(BasePage, "open", _noop, raising=False)


def _empty_driver() -> MagicMock:
    """A driver adapter over a page with nothing on it."""
    async def _none(*a, **k):
        return None

    async def _zero(*a, **k):
        return 0

    driver = MagicMock()
    driver.query_selector = _none
    driver.query_selector_all = _none
    driver.wait_for_selector = _none
    driver.goto = _none
    driver.locator_count = _zero
    return driver


@pytest.mark.parametrize("action, extra", _actions(), ids=_ids())
def test_a_missed_interaction_fails_the_step(action, extra, every_lookup_misses):
    page = MagicMock()
    page.url = "http://127.0.0.1/wherever"
    action._driver = lambda _page: _empty_driver()

    step = StepConfig(action=action.action_name, description="probe", extra=extra)
    result = asyncio.run(action.execute(page, step, MagicMock(),
                                        ExecutionContext(), None))

    assert result.status == "failed", (
        f"{action.action_name} reported {result.status!r} with nothing on the "
        f"page. This is the shape that made a 0-match selector look green."
    )
    assert action.action_name in (result.error or ""), (
        "the error should name the action that missed, so a run log points at "
        "the step rather than at the framework"
    )


# ── The two actions that promise a check ──────────────────────────────────────
#
# ti_view_secure and ti_logout both say "confirm" in their docstrings and
# neither did. ti_view_secure's `if flash:` made "no flash" indistinguishable
# from "flash", which is why log_in_and_view_the_secure_area reported 2/2 on a
# wrong password: the login step submits the form (true), and the step whose
# job is to notice it landed on /login instead said nothing.

def _secure_action_with_flash(flash, url="http://127.0.0.1/login?error=1"):
    from stepper.sites.ti.pages.secure_action import TiSecurePage
    from poms.ti.pages.secure_page import SecurePage

    action = TiSecurePage.TiViewSecureAction()
    action._driver = lambda _page: MagicMock()

    async def _flash(self):
        return flash

    async def _ready(self):
        return None

    page = MagicMock()
    page.url = url
    ctx = ExecutionContext()
    step = StepConfig(action=action.action_name, description="probe")
    return action, page, ctx, step, (SecurePage, _flash, _ready)


def test_view_secure_fails_when_the_secure_area_was_not_reached(monkeypatch):
    from poms.ti.pages.secure_page import SecurePage

    action, page, ctx, step, (cls, _flash, _ready) = _secure_action_with_flash(None)
    monkeypatch.setattr(cls, "get_flash_message", _flash)
    monkeypatch.setattr(cls, "wait_for_ready", _ready)

    result = asyncio.run(action.execute(page, step, MagicMock(), ctx, None))

    assert result.status == "failed", (
        "no flash means the login did not land — reporting passed here is what "
        "let a wrong password produce a 2/2 green run"
    )
    assert "login?error=1" in result.error, "the error should name where it ended up"


def test_view_secure_stores_the_flash_it_confirmed(monkeypatch):
    from poms.ti.pages.secure_page import SecurePage

    action, page, ctx, step, (cls, _flash, _ready) = _secure_action_with_flash(
        "You logged into a secure area!", url="http://127.0.0.1/secure")
    monkeypatch.setattr(cls, "get_flash_message", _flash)
    monkeypatch.setattr(cls, "wait_for_ready", _ready)

    result = asyncio.run(action.execute(page, step, MagicMock(), ctx, None))

    assert result.status == "passed"
    assert ctx.get("ti_secure_flash") == "You logged into a secure area!"
    assert result.output == {"ti_secure_flash": "You logged into a secure area!"}
