"""
main.py — Entry point. Wires all components together.

This is the ONLY file that knows about concrete classes.
Everything else depends on interfaces (DIP).

Two modes:
  1. JSON workflow  : python main.py --workflow workflows/search_and_add.json
  2. Natural language: python main.py --task "search Dune, add 5 books to reading list"
"""

from __future__ import annotations
import asyncio
import argparse
import json
import logging
import os
from pathlib import Path
from typing import NamedTuple


def _load_env() -> None:
    """Load .env into os.environ using python-dotenv.
    Looks in project root first, then stepper/ as fallback.
    Existing env vars are never overridden (override=False).
    Supports quoted values, export prefixes, and multi-line values.
    """
    from dotenv import load_dotenv
    _here = Path(__file__).resolve().parent
    for candidate in (_here.parent / ".env", _here / ".env"):
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            break


# Add src/ and repo root to path so all modules resolve regardless of cwd
import sys
_root_path   = str(Path(__file__).parent)
_src_path    = str(Path(__file__).parent / "src")
_parent_path = str(Path(__file__).parent.parent)  # repo root — where openLibrary/ lives
for _p in (_parent_path, _root_path, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from playwright.async_api import async_playwright

from poms.openLibrary.config import load_settings, validate_ai_config

from engine.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
from engine.actions.factory import build_default_registry
from engine.runner.step_runner import StepRunner, LoggingObserver
from engine.reporter.reporters import CompositeReporter, ConsoleReporter, JsonReporter, AllureReporter
from engine.reporter.test_report_reporter import TestReportReporter

logger = logging.getLogger(__name__)

# Absolute path to stepper/ — all output paths are anchored here so the tool
# produces identical folder structure regardless of which directory it is run from.
_stepper_root = Path(__file__).resolve().parent


class _RunSettings(NamedTuple):
    use_visual_ai: bool
    slow_mo: int
    browser: str
    storage_state_path: str | None


def _load_settings_safe() -> _RunSettings:
    try:
        settings = load_settings()
        validate_ai_config(settings)
        return _RunSettings(
            use_visual_ai=settings.use_visual_ai,
            slow_mo=settings.slow_mo_ms,
            browser=settings.browser,
            storage_state_path=settings.storage_state_path,
        )
    except Exception:
        return _RunSettings(use_visual_ai=False, slow_mo=300, browser="chromium", storage_state_path=None)


def _build_resolver(use_visual_ai: bool) -> "ElementResolver":
    ai_client = None
    if use_visual_ai:
        import anthropic
        ai_client = anthropic.Anthropic()
    resolver_factory = DefaultResolverFactory()
    return ElementResolver(
        strategies=resolver_factory.build_cascade(),
        ai_client=ai_client,
        use_visual_ai=use_visual_ai,
    )


def _build_reporters(run_label: str, cfg_browser: str, headless: bool, stepper_root: Path):
    test_reporter = TestReportReporter(
        reports_base=str(stepper_root / "reports"),
        test_name=run_label,
        browser=cfg_browser,
        headless=not headless,
    )
    reporters = [
        ConsoleReporter(),
        JsonReporter(str(stepper_root / "report.json")),
        test_reporter,
        AllureReporter(str(stepper_root / "reports" / "allure-results")),
    ]
    return CompositeReporter(reporters), test_reporter


async def _launch_browser(pw, cfg_browser: str, headless: bool, slow_mo: int):
    _launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
    return await _launchers.get(cfg_browser, pw.chromium).launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled"],
    )


def _serve_allure() -> None:
    import subprocess
    allure_dir = str(_stepper_root / "reports" / "allure-results")
    logger.info(f"Launching: allure serve {allure_dir}")
    subprocess.run(["allure", "serve", allure_dir])


async def run(
    workflow_path: str = None,
    task: str = None,
    headless: bool = True,
    allure_serve: bool = False,
    record_video: bool = False,
    variables: dict | None = None,
    resolver: "ElementResolver | None" = None,
    _browser=None,
):

    # ── 1. Planner ───────────────────────────────────────────────────────────
    if workflow_path:
        from engine.planner.planner import JsonFilePlanner
        planner = JsonFilePlanner(workflow_path, variables=variables)
    elif task:
        from engine.planner.planner import ClaudePlanner
        planner = ClaudePlanner()
    else:
        raise ValueError("Provide --workflow or --task")

    steps = planner.plan(task or "")
    logger.info(f"Planned {len(steps)} steps")

    # ── 2. Infrastructure ─────────────────────────────────────────────────────
    s = _load_settings_safe()
    use_visual_ai      = s.use_visual_ai
    slow_mo            = s.slow_mo
    cfg_browser        = s.browser
    storage_state_path = s.storage_state_path

    if resolver is None:
        resolver = _build_resolver(use_visual_ai)

    # ── 3. Reporters — absolute paths so output is always inside stepper/ ─────
    run_label = Path(workflow_path).stem if workflow_path else "task"
    reporter, test_reporter = _build_reporters(run_label, cfg_browser, headless, _stepper_root)

    # ── 4. Run ───────────────────────────────────────────────────────────────
    _owns_browser = _browser is None
    _pw_instance = None

    if _owns_browser:
        _pw_instance = await async_playwright().start()
        browser = await _launch_browser(_pw_instance, cfg_browser, headless, slow_mo)
    else:
        browser = _browser

    try:
        # Start suite first — TestReportReporter creates the run directory here.
        suite_name = workflow_path or task or "automation"
        reporter.start_suite(suite_name)

        # Wire terminal log and screenshots into the run-specific directory.
        # Screenshots go directly into the run directory — no separate temp folder.
        # Actions write here; TestReportReporter records the paths without copying.
        log_handler = None
        if test_reporter and test_reporter.manager.current_test_dir:
            log_path = test_reporter.manager.current_test_dir / "logs" / "run.log"
            log_handler = logging.FileHandler(log_path, encoding="utf-8")
            log_handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S"
            ))
            logging.getLogger().addHandler(log_handler)
            screenshots_dir = test_reporter.manager.get_screenshots_dir()
        else:
            screenshots_dir = _stepper_root / "artifacts" / "screenshots"

        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Build action registry now that we have the run-specific screenshots dir.
        action_registry = build_default_registry(screenshots_dir=screenshots_dir)

        # Each site registers its custom actions into the shared registry.
        # Adding a new site = add two lines here. Zero other changes. (OCP)
        from sites.openlibrary.pages.search_page import OLSearchPage
        from sites.openlibrary.pages.detail_page import OLDetailPage
        from sites.openlibrary.pages.reading_list_action import OLReadingListPage
        from sites.openlibrary.pages.login_action import OLLoginPage
        
        
        OLSearchPage.register(action_registry)
        OLDetailPage.register(action_registry, screenshots_dir=screenshots_dir)
        OLReadingListPage.register(action_registry)
        OLLoginPage.register(action_registry)

        context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
        if storage_state_path and Path(str(storage_state_path)).exists():
            context_kwargs["storage_state"] = str(storage_state_path)
            logger.info(f"Loaded session from {storage_state_path}")
        if record_video and test_reporter and test_reporter.manager.current_test_dir:
            videos_dir = test_reporter.manager.current_test_dir / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"] = str(videos_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 800}
            logger.info(f"Recording video → {videos_dir}")
        context = await browser.new_context(**context_kwargs)
        page    = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        runner = StepRunner(
            page=page,
            action_factory=action_registry,
            resolver=resolver,
            reporter=reporter,
            screenshots_dir=screenshots_dir,
        )
        runner.add_observer(LoggingObserver())

        # TEMPORAL COUPLING: RunWorkflowAction MUST be registered after StepRunner is
        # constructed. It closes over runner.run, so the runner must already exist.
        # Moving this block above the StepRunner construction will cause a NameError.
        from engine.actions.strategies import RunWorkflowAction
        base_dir = Path(workflow_path).parent if workflow_path else Path.cwd()
        action_registry.register(RunWorkflowAction(run_steps_callable=runner.run, base_dir=base_dir))

        results, _ = await runner.run(steps)
        reporter.finish_suite()

        if log_handler:
            logging.getLogger().removeHandler(log_handler)
            log_handler.close()

        _LOGIN_ACTIONS = {"ol_ensure_login", "sd_login", "ensure_login"}
        if storage_state_path and any(r.step.action in _LOGIN_ACTIONS for r in results):
            Path(str(storage_state_path)).parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(storage_state_path))
            logger.info(f"Session saved to {storage_state_path}")
        elif storage_state_path:
            logger.debug("Skipping storage_state write — no login action ran")

        await context.close()

    finally:
        if _owns_browser:
            await browser.close()
            if _pw_instance:
                await _pw_instance.stop()

    if allure_serve:
        _serve_allure()

    return results


async def _run_data_rows(rows: list[dict], cli_vars: dict, args) -> None:
    """Open one playwright instance and browser; run each data row in a fresh context."""
    # Build resolver once — reused across all rows (ElementResolver is stateless)
    s = _load_settings_safe()
    use_visual_ai = s.use_visual_ai
    slow_mo       = s.slow_mo
    cfg_browser   = s.browser

    resolver = _build_resolver(use_visual_ai)

    async with async_playwright() as pw:
        browser = await _launch_browser(pw, cfg_browser, not args.show, slow_mo)
        for i, row in enumerate(rows, 1):
            merged = {**row, **cli_vars}   # cli_vars wins over row values
            logger.info(f"[data-driven] row {i}/{len(rows)}: {merged}")
            await run(
                workflow_path=args.workflow,
                task=args.task,
                headless=not args.show,
                allure_serve=False,          # serve once at the end, not per row
                record_video=args.video,
                variables=merged,
                resolver=resolver,
                _browser=browser,
            )
        await browser.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    _load_env()

    parser = argparse.ArgumentParser(description="Stepper — AI Browser Automation")
    parser.add_argument("--workflow", help="Path to workflow JSON file")
    parser.add_argument("--task",     help="Natural language task description")
    parser.add_argument("--show",          action="store_true", help="Show browser window")
    parser.add_argument("--allure-serve",  action="store_true", help="Open Allure report in browser after run")
    parser.add_argument("--video",         action="store_true", help="Record video to test-*/videos/")
    parser.add_argument(
        "--vars",
        help='JSON string of variable overrides, e.g. \'{"query":"Foundation","limit":3}\'',
    )
    parser.add_argument(
        "--data",
        help="Path to a JSON file containing an array of variable objects — runs once per row",
    )
    args = parser.parse_args()

    # Parse --vars once (applies to every run, or overrides --data rows)
    cli_vars: dict = {}
    if args.vars:
        try:
            cli_vars = json.loads(args.vars)
        except json.JSONDecodeError as e:
            parser.error(f"--vars is not valid JSON: {e}")

    # --data: load the array and run all rows sharing one browser
    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            parser.error(f"--data file not found: {data_path}")
        rows: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            parser.error("--data file must contain a JSON array of objects")

        asyncio.run(_run_data_rows(rows, cli_vars, args))

        if args.allure_serve:
            _serve_allure()
        return

    # Single run (no --data)
    asyncio.run(run(
        workflow_path=args.workflow,
        task=args.task,
        headless=not args.show,
        allure_serve=args.allure_serve,
        record_video=args.video,
        variables=cli_vars or None,
    ))


if __name__ == "__main__":
    main()
