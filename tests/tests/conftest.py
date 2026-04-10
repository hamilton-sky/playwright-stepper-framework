import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# conftest.py is at automation/openlibrary/tests/conftest.py
# parents[2] = automation/  — adds it to sys.path so `from openlibrary.x` resolves
AUTOMATION_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT    = Path(__file__).resolve().parents[1]  # automation/openlibrary/
if str(AUTOMATION_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_ROOT))


def _load_env(path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(PROJECT_ROOT / ".env")

from shared_poms.config import load_settings
from shared_poms.auth import ensure_logged_in
from openlibrary.reporter import make_default_reporter
from openlibrary.orchestrator import BrowserSessionManager, FlowOrchestrator
from openlibrary.interfaces import ExamEvent


@pytest_asyncio.fixture(scope="session")
async def orch():
    """
    Session-scoped FlowOrchestrator — one browser for the whole test run.

    Benefits over per-test browser sessions:
      - Faster: browser launches once, session cookie reused
      - Cheaper: no repeated login overhead per test
      - Realistic: mirrors how a real user operates

    Use the function-scoped `reading_list_count_before` fixture to get a
    clean reading list state before each test.
    """
    settings = load_settings()
    reporter = make_default_reporter(settings.report_output, settings.logs_dir)
    reporter.on_event(ExamEvent(phase="setup", status="start", message="Starting browser session"))
    async with BrowserSessionManager(settings) as session:
        reporter.on_event(ExamEvent(phase="setup", status="start", message="Logging in to OpenLibrary…"))
        await ensure_logged_in(
            session.driver, settings.username, settings.password,
            settings.base_url,
            login_url=settings.login_url,
            max_login_attempts=settings.max_login_attempts,
        )
        reporter.on_event(ExamEvent(phase="setup", status="success", message="Logged in — session ready"))
        yield FlowOrchestrator(session.driver, settings, reporter)


@pytest_asyncio.fixture
async def reading_list_count_before(orch) -> int:
    """
    Clear the reading list via the shared session and return 0.
    Runs before each test — guarantees a clean slate without launching a new browser.
    """
    orch._reporter.on_event(ExamEvent(phase="setup", status="start", message="Clearing reading list before test…"))
    removed = await orch.clear()
    orch._reporter.on_event(ExamEvent(phase="setup", status="success", message=f"Reading list cleared ({removed} books removed)"))
    return 0
