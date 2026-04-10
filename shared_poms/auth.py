from __future__ import annotations

import asyncio
import logging

from shared_poms.interfaces import IBrowserDriver

logger = logging.getLogger(__name__)

_DEFAULT_LOGIN_URL     = "https://openlibrary.org/account/login"
_DEFAULT_MAX_ATTEMPTS  = 3


async def is_login_required(driver: IBrowserDriver) -> bool:
    if "login" in driver.current_url.lower():
        return True
    try:
        return await driver.locator_count("#username") > 0
    except Exception:
        return False


async def ensure_logged_in(
    driver: IBrowserDriver,
    username: str | None,
    password: str | None,
    base_url: str,
    *,
    login_url: str = _DEFAULT_LOGIN_URL,
    max_login_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> None:
    """
    Navigate to a protected page with networkidle wait (catches the login
    redirect reliably), then check login state with a positive selector
    before deciding whether to login.

    Login URL and max attempts come from Settings — no hardcoded strings here.
    """
    _LOGIN_FRAGMENT = "/account/login"
    _LOGGED_IN_SEL  = "a[href='/account']"
    protected       = f"{base_url.rstrip('/')}/account/books/want-to-read"

    logger.info("Navigating to protected page to check session: %s", protected)
    await driver.goto(protected, wait_until="domcontentloaded")
    logger.info("Navigation complete — current URL: %s", driver.current_url)

    try:
        logged_in = await driver.locator_count(_LOGGED_IN_SEL) > 0
    except Exception:
        logged_in = False

    if _LOGIN_FRAGMENT in driver.current_url:
        logger.info("Redirected to login page — session expired or not present")
        logged_in = False

    if logged_in:
        logger.info("ensure_logged_in: already logged in as %s", username)
        return

    if not username or not password:
        raise RuntimeError(
            "Login required but OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD "
            "are not set. Add them to your .env file."
        )

    logger.info("Login required — starting login flow for %s", username)
    await login(
        driver, username, password,
        login_url=login_url,
        max_attempts=max_login_attempts,
    )


async def login(
    driver: IBrowserDriver,
    username: str,
    password: str,
    *,
    login_url: str = _DEFAULT_LOGIN_URL,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Login to OpenLibrary with rate limiting and retry logic."""
    logger.info(f"Attempting login for: {username}")

    for attempt in range(max_attempts):
        try:
            logger.info("Login attempt %d/%d — navigating to %s", attempt + 1, max_attempts, login_url)
            await driver.goto(login_url, wait_until="domcontentloaded")
            logger.info("Login page loaded — waiting for #username field…")
            try:
                await driver.wait_for_selector("#username", timeout=45_000)
                logger.info("#username field ready")
            except Exception as e:
                logger.warning("#username not found after 45s: %s — proceeding anyway", e)

            logger.info("Filling credentials…")
            await driver.fill("#username", username)
            await asyncio.sleep(0.3)
            await driver.fill("#password", password)
            await asyncio.sleep(0.3)
            logger.info("Submitting login form…")
            await driver.click(".cta-btn--primary")
            await driver.wait_for_load_state("domcontentloaded")
            logger.info("Post-submit URL: %s", driver.current_url)

            if not await is_login_required(driver):
                logger.info("Login successful on attempt %d — URL: %s", attempt + 1, driver.current_url)
                return

            logger.warning("Login attempt %d: still on login page", attempt + 1)
            if attempt < max_attempts - 1:
                logger.info("Retrying in 2s…")
                await asyncio.sleep(2)

        except Exception as e:
            if attempt < max_attempts - 1:
                logger.warning(
                    "Login attempt %d raised %s: %s — retrying in 2s…",
                    attempt + 1, type(e).__name__, e,
                )
                await asyncio.sleep(2)
            else:
                raise RuntimeError(
                    f"Login failed after {max_attempts} attempts: {e}. "
                    "Check OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD."
                ) from e

    raise RuntimeError(
        f"Login failed after {max_attempts} attempts. "
        "Check OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD."
    )
