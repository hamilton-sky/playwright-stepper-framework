import json
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

_stepper_dir = Path(__file__).resolve().parent.parent
_repo_root   = _stepper_dir.parent
for _p in (_repo_root, _stepper_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from engine.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
from poms.openLibrary.config import load_settings, validate_ai_config
from main import _load_env

_load_env()   # load .env before any fixture reads os.environ


def pytest_addoption(parser):
    try:
        parser.addoption("--headed", action="store_true", default=False,
                         help="Run browser in headed (visible) mode")
    except Exception:
        pass
    try:
        parser.addoption(
            "--workflow",
            default=None,
            help="Workflow filename or path for data-driven test "
                 "(e.g. ol_search_and_add.json or an absolute path)",
        )
    except Exception:
        pass
    try:
        parser.addoption(
            "--data",
            default=None,
            help="Path to a JSON array file of variable objects for the data-driven test",
        )
    except Exception:
        pass
    try:
        parser.addoption("--case", type=int, default=0,
                         help="Index of the test case to run (default: 0)")
    except Exception:
        pass
    try:
        parser.addoption("--all-cases", action="store_true", default=False,
                         help="Run all cases from the --data file")
    except Exception:
        pass


def pytest_generate_tests(metafunc):
    """Parametrize test_case fixture from --data file when --workflow and --data are given."""
    if "test_case" not in metafunc.fixturenames:
        return

    workflow  = metafunc.config.getoption("--workflow")
    data_flag = metafunc.config.getoption("--data")

    if not workflow or not data_flag:
        metafunc.parametrize(
            "test_case",
            [pytest.param({}, marks=pytest.mark.skip(
                reason="--workflow and --data are both required for data-driven tests"
            ))],
        )
        return

    data_path = Path(data_flag)
    if not data_path.exists():
        raise FileNotFoundError(f"--data file not found: {data_path}")

    cases = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError(f"--data file must contain a JSON array: {data_path}")

    if metafunc.config.getoption("--all-cases"):
        selected = cases
    else:
        idx = metafunc.config.getoption("--case")
        if idx < 0 or idx >= len(cases):
            raise ValueError(
                f"--case {idx} is out of range: data file has {len(cases)} case(s) (0-{len(cases)-1})"
            )
        selected = [cases[idx]]

    ids = [c.get("comment", c.get("query", str(i))) for i, c in enumerate(selected)]
    metafunc.parametrize("test_case", selected, ids=ids)


@pytest_asyncio.fixture(scope="session", loop_scope="session") # Add loop_scope here
async def stepper_browser(request):
    """One browser for the entire test session."""
    try:
        settings    = load_settings()
        slow_mo     = settings.slow_mo_ms
        cfg_browser = settings.browser
    except Exception:
        slow_mo     = 0
        cfg_browser = "chromium"

    headless = not request.config.getoption("--headed")
    async with async_playwright() as pw:
        _launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
        browser = await _launchers.get(cfg_browser, pw.chromium).launch(
            headless=headless, slow_mo=slow_mo
        )
        yield browser
        await browser.close()


@pytest.fixture(scope="session")
def stepper_resolver():
    """One ElementResolver for the entire test session (MiniLM loaded once)."""
    try:
        settings      = load_settings()
        validate_ai_config(settings)
        use_visual_ai = settings.use_visual_ai
    except Exception:
        use_visual_ai = False

    ai_client = None
    if use_visual_ai:
        import anthropic
        ai_client = anthropic.Anthropic()

    factory = DefaultResolverFactory()
    return ElementResolver(
        strategies=factory.build_cascade(),
        ai_client=ai_client,
        use_visual_ai=use_visual_ai,
    )
