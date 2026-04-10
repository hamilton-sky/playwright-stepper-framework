"""
runner/api.py — Programmatic API for running Stepper workflows.

Lets exam functions, tests, and scripts run steps through the full
Stepper pipeline (resolver cascade, retry, observer, reporter)
without going through main.py's CLI.

Two usage patterns:

  1. One-shot (simple):
       results, ctx = await run_steps([{...}])
     Launches a browser, runs the steps, closes the browser.
     One browser per call — fine for isolated scripts.

  2. Shared session (efficient for tests):
       async with StepperSession() as session:
           results, ctx = await session.run([{...}])
           results, ctx = await session.run([{...}], initial_context=ctx)
     One browser for all calls — session cookie reused, no re-login.
     Registry and resolver built once, not per call.
"""
from __future__ import annotations
import logging
from pathlib import Path

from stepper.interfaces import ExecutionContext, StepResult
from stepper.planner.planner import _dict_to_step

logger = logging.getLogger(__name__)


# ── Shared session ─────────────────────────────────────────────────────────────

class StepperSession:
    """
    Context manager that holds one browser + one pipeline for multiple run() calls.

    Usage:
        async with StepperSession() as session:
            _, ctx  = await session.run([{"action": "ol_collect_books", ...}])
            ctx = ExecutionContext()
            ctx.collected_items = urls
            await session.run([{"action": "ol_add_to_shelf"}],
                              initial_context=ctx)

    Benefits over run_steps():
      - One browser launch for all steps
      - Registry and resolver built once
      - storage_state.json loaded once, saved on exit
    """

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw       = None
        self._browser  = None
        self._ctx      = None
        self._page     = None
        self._runner   = None
        self._reporter = None
        self._settings = None

    async def __aenter__(self) -> "StepperSession":
        from playwright.async_api import async_playwright

        from shared_poms.config import load_settings
        from stepper.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
        from stepper.actions.factory import build_default_registry
        from stepper.runner.step_runner import StepRunner, LoggingObserver
        from stepper.reporter.reporters import CompositeReporter, ConsoleReporter, JsonReporter, AllureReporter
        from sites.openlibrary.pages.search_page import OLSearchPage
        from sites.openlibrary.pages.detail_page import OLDetailPage
        from sites.openlibrary.pages.reading_list_action import OLReadingListPage

        self._settings = load_settings()

        resolver = ElementResolver(
            strategies=DefaultResolverFactory().build_cascade(),
            use_visual_ai=self._settings.use_visual_ai,
        )
        registry = build_default_registry()
        OLSearchPage.register(registry)
        OLDetailPage.register(registry)
        OLReadingListPage.register(registry)

        self._reporter = CompositeReporter([
            ConsoleReporter(),
            JsonReporter("report.json"),
            AllureReporter("reports/allure-results"),   # always on — like logs
        ])

        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            slow_mo=self._settings.slow_mo_ms,
        )

        context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
        if self._settings.storage_state_path.exists():
            context_kwargs["storage_state"] = str(self._settings.storage_state_path)

        self._ctx  = await self._browser.new_context(**context_kwargs)
        self._page = await self._ctx.new_page()

        self._runner = StepRunner(
            page=self._page,
            action_factory=registry,
            resolver=resolver,
            reporter=self._reporter,
        )
        self._runner.add_observer(LoggingObserver())

        # Register runtime subflow action after runner exists
        from stepper.actions.strategies import RunWorkflowAction
        registry.register(RunWorkflowAction(run_steps_callable=self._runner.run, base_dir=Path.cwd()))

        return self

    async def run(
        self,
        steps: list[dict],
        initial_context: ExecutionContext | None = None,
        suite_name: str = "run_steps",
    ) -> tuple[list[StepResult], ExecutionContext]:
        """Run a list of step dicts through the shared pipeline."""
        step_configs = [_dict_to_step(s) for s in steps]
        self._reporter.start_suite(suite_name)
        results, ctx = await self._runner.run(step_configs, context=initial_context)
        self._reporter.finish_suite()
        return results, ctx

    async def __aexit__(self, *_) -> None:
        if self._ctx:
            self._settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await self._ctx.storage_state(
                path=str(self._settings.storage_state_path)
            )
            await self._ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


# ── One-shot helper (backwards compatible) ────────────────────────────────────

async def run_steps(
    steps: list[dict],
    initial_context: ExecutionContext | None = None,
    headless: bool = True,
) -> tuple[list[StepResult], ExecutionContext]:
    """
    Run steps in a fresh browser session.
    For multiple sequential calls, prefer StepperSession to avoid
    launching a new browser per call.
    """
    async with StepperSession(headless=headless) as session:
        return await session.run(steps, initial_context=initial_context)
