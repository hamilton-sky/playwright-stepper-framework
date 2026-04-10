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


def _load_env(path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:   # don't override real env vars
            os.environ[key] = value


_load_env()

# Add src/ and repo root to path so all modules resolve regardless of cwd
import sys
_root_path   = str(Path(__file__).parent)
_src_path    = str(Path(__file__).parent / "src")
_parent_path = str(Path(__file__).parent.parent)  # automation/ — where openlibrary/ lives
for _p in (_parent_path, _root_path, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from playwright.async_api import async_playwright

from shared_poms.config import load_settings

from stepper.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
from stepper.actions.factory import build_default_registry
from stepper.runner.step_runner import StepRunner, LoggingObserver
from stepper.reporter.reporters import CompositeReporter, ConsoleReporter, JsonReporter, AllureReporter
from stepper.reporter.test_report_reporter import TestReportReporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run(
    workflow_path: str = None,
    task: str = None,
    headless: bool = True,
    allure_serve: bool = False,
    record_video: bool = False,
    variables: dict | None = None,
):

    # ── 1. Planner ───────────────────────────────────────────────────────────
    if workflow_path:
        from stepper.planner.planner import JsonFilePlanner
        planner = JsonFilePlanner(workflow_path, variables=variables)
    elif task:
        from stepper.planner.planner import ClaudePlanner
        planner = ClaudePlanner()
    else:
        raise ValueError("Provide --workflow or --task")

    steps = planner.plan(task or "")
    logger.info(f"Planned {len(steps)} steps")

    # ── 2. Infrastructure ─────────────────────────────────────────────────────
    try:
        settings = load_settings()
        use_visual_ai   = settings.use_visual_ai
        slow_mo         = settings.slow_mo_ms
        cfg_browser     = settings.browser
        cfg_headless    = not headless   # headless arg = show browser, settings = headless flag
        screenshots_dir = settings.screenshots_dir
    except Exception:
        use_visual_ai   = False
        slow_mo         = 300
        cfg_browser     = "chromium"
        cfg_headless    = not headless
        screenshots_dir = Path("artifacts/screenshots")

    ai_client = None
    if use_visual_ai:
        import anthropic
        ai_client = anthropic.Anthropic()

    resolver_factory = DefaultResolverFactory()
    resolver = ElementResolver(
        strategies=resolver_factory.build_cascade(),
        ai_client=ai_client,
        use_visual_ai=use_visual_ai,
    )

    action_registry = build_default_registry(screenshots_dir=screenshots_dir)

    # ── Page Modules (site-specific actions) ─────────────────────────────────
    # Each module registers its ol_* actions into the shared registry.
    # Adding a new site = add two lines here. Zero other changes. (OCP)
    from sites.openlibrary.pages.search_page import OLSearchPage
    from sites.openlibrary.pages.detail_page import OLDetailPage
    from sites.openlibrary.pages.reading_list_action import OLReadingListPage
    OLSearchPage.register(action_registry)
    OLDetailPage.register(action_registry)
    OLReadingListPage.register(action_registry)

    run_label = Path(workflow_path).stem if workflow_path else "task"
    reporters = [
        ConsoleReporter(),
        JsonReporter("report.json"),
        TestReportReporter(
            reports_base="reports",
            test_name=run_label,
            browser=cfg_browser,
            headless=cfg_headless,
        ),
        AllureReporter("reports/allure-results"),   # always on — like logs
    ]
    reporter = CompositeReporter(reporters)

    # ── 3. Run ───────────────────────────────────────────────────────────────
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, slow_mo=slow_mo)
        storage_state_path = settings.storage_state_path if 'settings' in dir() else None

        # Start suite first so TestReportReporter creates the test directory
        suite_name   = workflow_path or task or "automation"
        test_reporter = next((r for r in reporters if isinstance(r, TestReportReporter)), None)
        reporter.start_suite(suite_name)

        # Wire terminal log → test-*/logs/run.log
        log_handler = None
        if test_reporter and test_reporter.manager.current_test_dir:
            log_path = test_reporter.manager.current_test_dir / "logs" / "run.log"
            log_handler = logging.FileHandler(log_path, encoding="utf-8")
            log_handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S"
            ))
            logging.getLogger().addHandler(log_handler)

        context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
        if storage_state_path and storage_state_path.exists():
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

        runner = StepRunner(
            page=page,
            action_factory=action_registry,
            resolver=resolver,
            reporter=reporter,
            screenshots_dir=screenshots_dir,
        )
        runner.add_observer(LoggingObserver())

        # Register runtime subflow action after runner exists (needs runner.run callback)
        from stepper.actions.strategies import RunWorkflowAction
        base_dir = Path(workflow_path).parent if workflow_path else Path.cwd()
        action_registry.register(RunWorkflowAction(run_steps_callable=runner.run, base_dir=base_dir))

        results, _ = await runner.run(steps)
        reporter.finish_suite()

        if log_handler:
            logging.getLogger().removeHandler(log_handler)
            log_handler.close()

        if storage_state_path:
            storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(storage_state_path))
            logger.info(f"Session saved to {storage_state_path}")

        await browser.close()

    if allure_serve:
        import subprocess
        logger.info("Launching: allure serve reports/allure-results")
        subprocess.run(["allure", "serve", "reports/allure-results"])

    return results


def main():
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

    # --data: load the array and run once per row
    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            parser.error(f"--data file not found: {data_path}")
        rows: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            parser.error("--data file must contain a JSON array of objects")

        for i, row in enumerate(rows, 1):
            merged = {**row, **cli_vars}   # cli_vars wins over row values
            logger.info(f"[data-driven] row {i}/{len(rows)}: {merged}")
            asyncio.run(run(
                workflow_path=args.workflow,
                task=args.task,
                headless=not args.show,
                allure_serve=False,          # serve once at the end, not per row
                record_video=args.video,
                variables=merged,
            ))

        if args.allure_serve:
            import subprocess
            subprocess.run(["allure", "serve", "reports/allure-results"])
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
