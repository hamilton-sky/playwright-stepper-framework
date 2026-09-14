"""
LoginPage.submit() must wait for the submit to resolve, not just for a load state.

The bug this guards against is the repo's own pitfall #5 in a new costume: not a
missing `await`, but an `await` on the wrong thing.

    await self._interact(self.Locators.SUBMIT, "click")
    await self._driver.wait_for_load_state("domcontentloaded")

`wait_for_load_state` reports on the *current* document. Immediately after the
click that document is still the login page, which is already loaded, so it
returns at once — before the new page commits. `sd_login` then calls
is_logged_in(), counts `.app_logo` on the old DOM, finds zero, asks
get_error_message(), finds nothing either, and reports:

    sd_login: login failed — unknown error

for a login that was about to succeed. It fails only when the navigation is
slower than the check, so it passes locally and on most CI runs and then does
not, which is the worst shape a test failure can have.

These tests drive a driver double. No browser, no network, no SauceDemo.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from poms.saucedemo.pages.login_page import LoginPage


@pytest.fixture
def driver() -> MagicMock:
    d = MagicMock()
    d.wait_for_selector = AsyncMock(return_value=MagicMock())
    d.wait_for_load_state = AsyncMock()
    d.locator_count = AsyncMock(return_value=0)
    return d


@pytest.fixture
def page(driver) -> LoginPage:
    """Driver-only mode — no resolver, which is enough to exercise submit()."""
    login = LoginPage(driver, "https://www.saucedemo.com")
    # The click itself is _interact's business and is covered elsewhere; stub it
    # so these tests speak only about what happens after the click.
    login._interact = AsyncMock(return_value=True)  # type: ignore[method-assign]
    return login


async def test_submit_waits_for_an_outcome_not_just_a_load_state(page, driver):
    """
    The fix, stated directly: something must wait on a selector that only exists
    after the submit resolved. A load state alone cannot distinguish "navigated"
    from "has not navigated yet".
    """
    await page.submit()

    assert driver.wait_for_selector.await_count == 1, (
        "submit() returned without waiting for any post-submit element"
    )


async def test_the_wait_accepts_either_outcome(page, driver):
    """
    Success and failure both have to end the wait. Waiting only for the app logo
    would stall the full timeout on every genuine bad-credentials run, and turn
    a clear error message into a timeout.
    """
    await page.submit()

    selector = driver.wait_for_selector.await_args.args[0]
    assert LoginPage.Locators.APP_LOGO in selector, "success outcome not awaited"
    assert LoginPage.Locators.ERROR_MSG in selector, "failure outcome not awaited"


async def test_the_wait_is_bounded(page, driver):
    """A POM that can hang forever turns a failed step into a hung run."""
    await page.submit()

    timeout = driver.wait_for_selector.await_args.kwargs.get("timeout")
    assert timeout is not None, "no timeout passed — this wait could hang"
    assert 0 < timeout <= 30_000


async def test_the_click_happens_before_the_wait(page, driver):
    """Waiting first would wait on the pre-submit page and prove nothing."""
    order: list[str] = []

    page._interact = AsyncMock(side_effect=lambda *a, **kw: order.append("click"))  # type: ignore[method-assign]
    driver.wait_for_selector = AsyncMock(side_effect=lambda *a, **kw: order.append("wait"))

    await page.submit()

    assert order == ["click", "wait"]


async def test_a_timeout_does_not_raise_out_of_the_pom(page, driver):
    """
    A page that never settles is a failed assertion for the caller to report,
    not an exception from a POM method. The layer contract is that POMs return
    data and never raise at their callers.
    """
    driver.wait_for_selector = AsyncMock(side_effect=TimeoutError("30s exceeded"))

    await page.submit()   # must not raise

    assert driver.wait_for_load_state.await_count == 1, (
        "a timed-out wait should still fall through to the load-state check"
    )


async def test_is_logged_in_reads_the_app_logo(driver):
    """
    The signal submit() is waiting on. If this ever stops being the thing that
    marks a logged-in page, the wait above is waiting for the wrong element.
    """
    login = LoginPage(driver, "https://www.saucedemo.com")

    driver.locator_count = AsyncMock(return_value=1)
    assert await login.is_logged_in() is True

    driver.locator_count = AsyncMock(return_value=0)
    assert await login.is_logged_in() is False


async def test_is_logged_in_is_false_rather_than_raising_on_a_dead_page(driver):
    """It is called before login too, on a page that may not have loaded yet."""
    login = LoginPage(driver, "https://www.saucedemo.com")
    driver.locator_count = AsyncMock(side_effect=RuntimeError("context destroyed"))

    assert await login.is_logged_in() is False
