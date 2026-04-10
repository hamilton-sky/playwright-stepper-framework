# This file intentionally left minimal — exam suite moved to exam/
# Run the exam solution from: cd ../exam && pytest tests/ -v
#
# Stepper framework solution: python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

# Ensure shared_poms is importable regardless of cwd
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from shared_poms.driver import PlaywrightDriver
from shared_poms.config import load_settings
from shared_poms.auth import ensure_logged_in


def _has_credentials() -> bool:
    return bool(os.environ.get("OPENLIBRARY_USERNAME") and os.environ.get("OPENLIBRARY_PASSWORD"))


requires_auth = pytest.mark.skipif(
    not _has_credentials() and not load_settings().storage_state_path.exists(),
    reason="No saved session and no OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD set",
)


def pytest_addoption(parser):
    parser.addoption("--headed", action="store_true", default=False, help="Run browser in headed mode")


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest_asyncio.fixture(scope="session")
async def browser(request):
    headless = not request.config.getoption("--headed")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        yield browser
        await browser.close()


@pytest_asyncio.fixture(scope="session")
async def _authed_storage_state(browser, settings):
    """
    Runs once per session. Performs login if needed and returns path to
    storage_state.json so every test context can load the saved cookies.
    """
    if settings.storage_state_path and settings.storage_state_path.exists():
        return str(settings.storage_state_path)  # already have a session

    if not _has_credentials():
        return None  # no creds — auth tests will be skipped

    # Login once using a dedicated context, then save the session.
    # We navigate to a protected page AFTER login to confirm the session
    # is fully established before saving — prevents saving a stale/partial state.
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    driver = PlaywrightDriver(page)
    await ensure_logged_in(
        driver,
        os.environ["OPENLIBRARY_USERNAME"],
        os.environ["OPENLIBRARY_PASSWORD"],
        settings.base_url,
    )
    # Navigate to a protected page to confirm session is live before saving.
    import asyncio as _asyncio
    await _asyncio.sleep(1)  # let session cookies fully commit
    await driver.goto(
        f"{settings.base_url}/account/books/want-to-read",
        wait_until="domcontentloaded",
    )
    settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(settings.storage_state_path))
    await context.close()
    return str(settings.storage_state_path)


@pytest_asyncio.fixture
async def page(browser, settings, _authed_storage_state):
    """
    Fresh browser context + page per test.
    Loads saved login cookies when available so auth tests work.
    """
    ctx_kwargs = {"viewport": {"width": 1280, "height": 800}}
    if _authed_storage_state:
        ctx_kwargs["storage_state"] = _authed_storage_state
    context = await browser.new_context(**ctx_kwargs)
    page = await context.new_page()
    yield page
    await context.close()


@pytest_asyncio.fixture
async def driver(page):
    """PlaywrightDriver wrapping the raw Playwright page."""
    return PlaywrightDriver(page)
