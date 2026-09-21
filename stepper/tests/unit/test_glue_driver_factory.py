"""
GlueAction's driver adapter is injected, not hardcoded (ticket T6).

ARCHITECTURE.md has always claimed "swap the browser adapter → touches
existing code? No". It was not true: _driver() imported PlaywrightDriver and
constructed it by name, so swapping the adapter meant editing the base class
every glue action in the tree inherits from. That is leak L7.

No browser here. poms/shared/driver.py no longer imports Playwright at module
scope (T7), so PlaywrightDriver can be constructed against a stub page.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stepper.engine.interfaces import StepResult
from stepper.engine.pages.glue_action import (
    GlueAction, get_driver_factory, reset_driver_factory, set_driver_factory,
)


@pytest.fixture(autouse=True)
def restore_factory():
    """A swap is process-wide; no test may leak one into the next."""
    previous = get_driver_factory()
    yield
    set_driver_factory(previous)


class _Probe(GlueAction):
    action_name = "probe"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        return StepResult(step=step, status="passed")


class _FakeDriver:
    def __init__(self, page):
        self.page = page


# ── The default ───────────────────────────────────────────────────────────────

def test_the_default_adapter_is_the_playwright_one():
    from poms.shared.driver import PlaywrightDriver

    driver = _Probe()._driver(MagicMock())

    assert isinstance(driver, PlaywrightDriver)


def test_the_default_wraps_the_page_it_was_given():
    page = MagicMock()

    driver = _Probe()._driver(page)

    assert driver.current_url is page.url


# ── Swapping it ───────────────────────────────────────────────────────────────

def test_a_swapped_factory_is_what_glue_actions_build():
    set_driver_factory(_FakeDriver)
    page = MagicMock()

    driver = _Probe()._driver(page)

    assert isinstance(driver, _FakeDriver)
    assert driver.page is page


def test_swapping_returns_the_previous_factory_so_it_can_be_restored():
    previous = set_driver_factory(_FakeDriver)

    assert set_driver_factory(previous) is _FakeDriver
    assert get_driver_factory() is previous


def test_reset_restores_the_playwright_default():
    from poms.shared.driver import PlaywrightDriver

    set_driver_factory(_FakeDriver)
    reset_driver_factory()

    assert isinstance(_Probe()._driver(MagicMock()), PlaywrightDriver)


def test_a_swap_reaches_every_glue_action_not_just_new_ones():
    """
    Actions are registered once at startup and live for the whole process, so
    the factory has to be read per call — an action built before the swap must
    still see it.
    """
    action = _Probe()
    set_driver_factory(_FakeDriver)

    assert isinstance(action._driver(MagicMock()), _FakeDriver)


# ── Per-action override ───────────────────────────────────────────────────────

def test_an_action_can_override_the_factory_for_itself():
    class _Special(GlueAction):
        action_name = "special"
        driver_factory = staticmethod(_FakeDriver)

        async def _execute(self, page, step, resolver, context, behaviour=None):
            return StepResult(step=step, status="passed")

    from poms.shared.driver import PlaywrightDriver

    assert isinstance(_Special()._driver(MagicMock()), _FakeDriver)
    assert isinstance(_Probe()._driver(MagicMock()), PlaywrightDriver)


# ── The injection contract is unchanged ───────────────────────────────────────

def test_build_pom_still_demands_resolver_and_behaviour():
    """
    T6 changes where the driver comes from, not the rule that a POM cannot be
    built without a resolver. See .claude/rules/glue-layer.md.
    """
    class _Pom:
        def __init__(self, driver, base_url, *, page, resolver, behaviour):
            self.resolver = resolver

    probe = _Probe()

    with pytest.raises(TypeError):
        probe._build_pom(_Pom, MagicMock(), "http://x", page=MagicMock())

    built = probe._build_pom(_Pom, MagicMock(), "http://x",
                            page=MagicMock(), resolver="r", behaviour=None)
    assert built.resolver == "r"
