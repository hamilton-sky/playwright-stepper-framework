"""
main.py — Entry point. Wires all components together.

Two modes:
  1. JSON workflow  : python main.py --workflow workflows/search_and_add.json
  2. Natural language: python main.py --task "search Dune, add 5 books to reading list"
"""

from __future__ import annotations
import asyncio
import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add src/ and repo root to path so all modules resolve regardless of cwd
_root_path   = str(Path(__file__).parent)
_src_path    = str(Path(__file__).parent / "src")
_parent_path = str(Path(__file__).parent.parent)
for _p in (_parent_path, _root_path, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from playwright.async_api import async_playwright

from bootstrap.settings  import load_env, load_settings_safe
from bootstrap.infra     import build_resolver, launch_browser, register_all_sites
from bootstrap.reporting import build_reporters, serve_allure

from engine.actions.factory      import build_default_registry
from engine.actions.strategies   import RunWorkflowAction
from engine.runner.step_runner   import StepRunner, LoggingObserver

logger = logging.getLogger(__name__)

_stepper_root = Path(__file__).resolve().parent


def _extract_site(workflow_path: str | None) -> str:
    if not workflow_path:
        return "shared"
    parts = Path(workflow_path).parts
    for i, part in enumerate(parts):
        if part == "sites" and i + 1 < len(parts):
            return parts[i + 1]
    return "shared"


def _site_storage_state(workflow_path: str | None, stepper_root: Path) -> Path | None:
    """Return storage state path for sites that need session persistence.

    Only OpenLibrary requires saved sessions (logged-in state across runs).
    Other sites (SauceDemo, phpTravels) log in fresh each run — no persistence needed.
    """
    _SITES_WITH_PERSISTENCE = {"openlibrary"}
    site = _extract_site(workflow_path)
    if site in _SITES_WITH_PERSISTENCE:
        return stepper_root / "sites" / site / "artifacts" / "storage_state.json"
    return None


def _build_ci_summary(results, workflow_path, resolver, duration_s: float) -> dict:
    """Build structured JSON summary for --ci output."""
    steps = []
    for r in results:
        steps.append({
            "description": r.step.description,
            "action":      r.step.action,
            "status":      r.status,
            "duration_ms": r.duration_ms,
            "confidence":  r.confidence,
            "error":       r.error or None,
        })
    passed  = sum(1 for r in results if r.status == "passed")
    failed  = sum(1 for r in results if r.status == "failed")
    healed  = sum(1 for r in results if r.status == "healed")
    skipped = sum(1 for r in results if r.status == "skipped")

    drift_score = None
    if hasattr(resolver, "_drift_log"):
        recent = resolver._drift_log.latest(1)
        if recent:
            drift_score = recent[0].get("drift_score")

    return {
        "workflow":    workflow_path,
        "total_steps": len(results),
        "passed":      passed,
        "failed":      failed,
        "healed":      healed,
        "skipped":     skipped,
        "duration_s":  round(duration_s, 3),
        "drift_score": drift_score,
        "steps":       steps,
    }


async def run(
    workflow_path: str | None = None,
    task: str | None = None,
    headless: bool = True,
    allure_serve: bool = False,
    record_video: bool = False,
    variables: dict | None = None,
    resolver=None,
    _browser=None,
    max_heal_attempts: int = 0,
    shadow: bool = False,
    ci: bool = False,
    ci_output: str | None = None,
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
    s = load_settings_safe()
    # Each site owns its own storage state; derive path from workflow location
    s = s._replace(storage_state_path=_site_storage_state(workflow_path, _stepper_root))
    if resolver is None:
        resolver = build_resolver(s.use_visual_ai)

    if shadow:
        from engine.resolvers.shadow_runner import ShadowRunner, DriftLog
        from engine.resolvers.element_resolver import DefaultResolverFactory
        drift_path = _stepper_root / "sites" / _extract_site(workflow_path) / "artifacts" / "drift_log.json"
        resolver = ShadowRunner(resolver, DefaultResolverFactory().build_cascade(), DriftLog(drift_path))
        logger.info("👁  Shadow mode enabled — drift log → %s", drift_path)

    # ── 3. Reporters ──────────────────────────────────────────────────────────
    run_label = Path(workflow_path).stem if workflow_path else "task"
    reporter, test_reporter = build_reporters(run_label, s.browser, headless, _stepper_root)

    # ── 4. Run ───────────────────────────────────────────────────────────────
    _owns_browser = _browser is None
    _pw_instance  = None

    if _owns_browser:
        _pw_instance = await async_playwright().start()
        browser = await launch_browser(_pw_instance, s.browser, headless, s.slow_mo)
    else:
        browser = _browser

    try:
        suite_name = workflow_path or task or "automation"
        reporter.start_suite(suite_name)

        log_handler = None
        if test_reporter and test_reporter.manager.current_test_dir:
            log_path = test_reporter.manager.current_test_dir / "logs" / "run.log"
            log_handler = logging.FileHandler(log_path, encoding="utf-8")
            log_handler.setLevel(logging.DEBUG)   # file gets DEBUG; console stays INFO
            log_handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S"
            ))
            logging.getLogger().addHandler(log_handler)
            screenshots_dir = test_reporter.manager.get_screenshots_dir()
        else:
            screenshots_dir = _stepper_root / "sites" / "openlibrary" / "artifacts" / "screenshots"

        screenshots_dir.mkdir(parents=True, exist_ok=True)

        from poms.shared.driver import PlaywrightBrowserLauncher
        browser_launcher = PlaywrightBrowserLauncher(
            headless=headless,
            storage_state_path=Path(str(s.storage_state_path)) if s.storage_state_path else None,
        )
        action_registry = build_default_registry(
            screenshots_dir=screenshots_dir,
            browser_launcher=browser_launcher,
        )
        register_all_sites(action_registry, _stepper_root, screenshots_dir=screenshots_dir)

        context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
        if s.storage_state_path and Path(str(s.storage_state_path)).exists():
            context_kwargs["storage_state"] = str(s.storage_state_path)
            logger.info(f"Loaded session from {s.storage_state_path}")
        if record_video and test_reporter and test_reporter.manager.current_test_dir:
            videos_dir = test_reporter.manager.current_test_dir / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            context_kwargs["record_video_dir"]  = str(videos_dir)
            context_kwargs["record_video_size"] = {"width": 1280, "height": 800}
            logger.info(f"Recording video → {videos_dir}")

        context = await browser.new_context(**context_kwargs)
        page    = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        heal_cache = None
        if workflow_path:
            from engine.healer.healing_cache import HealCache
            cache_path = _stepper_root / "sites" / _extract_site(workflow_path) / "artifacts" / "heal_cache.json"
            heal_cache = HealCache(cache_path)

        healer = None
        if max_heal_attempts > 0:
            import os
            if os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY"):
                from engine.ai.service import AIService
                from engine.healer.ai_healer import AiHealer
                from engine.planner.schema_extractor import ActionSchemaExtractor
                schema = ActionSchemaExtractor.extract(action_registry)
                healer = AiHealer(action_schema=schema, ai_service=AIService())
                logger.info(f"⚕ Self-healing enabled (max {max_heal_attempts} attempt(s) per step)")
            else:
                logger.warning("⚕ --heal requested but no LLM API key found — healing disabled")

        runner = StepRunner(
            page=page,
            action_factory=action_registry,
            resolver=resolver,
            reporter=reporter,
            screenshots_dir=screenshots_dir,
            healer=healer,
            max_heal_attempts=max_heal_attempts,
            cache=heal_cache,
        )
        runner.add_observer(LoggingObserver())

        base_dir = Path(workflow_path).parent if workflow_path else Path.cwd()
        action_registry.register(RunWorkflowAction(run_steps_callable=runner.run, base_dir=base_dir))

        _run_start = time.monotonic()
        results, _ = await runner.run(steps)
        _run_duration = time.monotonic() - _run_start

        reporter.finish_suite()

        if ci:
            summary = _build_ci_summary(results, workflow_path, resolver, _run_duration)
            print(json.dumps(summary, indent=2))
            if ci_output:
                Path(ci_output).write_text(json.dumps(summary, indent=2), encoding="utf-8")
                logger.info(f"CI summary written to {ci_output}")

        drift_log = getattr(resolver, "_drift_log", None)
        if shadow and drift_log is not None:
            drift_log.flush()

        if log_handler:
            logging.getLogger().removeHandler(log_handler)
            log_handler.close()

        _LOGIN_ACTIONS = {"ol_ensure_login", "sd_login", "ensure_login"}
        if s.storage_state_path and any(r.step.action in _LOGIN_ACTIONS for r in results):
            Path(str(s.storage_state_path)).parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(s.storage_state_path))
            logger.info(f"Session saved to {s.storage_state_path}")
        elif s.storage_state_path:
            logger.debug("Skipping storage_state write — no login action ran")

        await context.close()

    finally:
        if _owns_browser:
            await browser.close()
            if _pw_instance:
                await _pw_instance.stop()

    if allure_serve:
        serve_allure(_stepper_root)

    return results


def apply_heals(workflow_path: Path, auto_yes: bool) -> None:
    """Read heal_suggestions.json, show diff, and optionally patch workflow JSON."""
    stepper_root = Path(__file__).parent
    reports_dir  = stepper_root / "reports"

    # Search reports/ for the most recent non-empty heal_suggestions.json,
    # then fall back to legacy artifacts/ locations.
    report_candidates = sorted(
        reports_dir.glob("*/heal_suggestions.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if reports_dir.exists() else []

    legacy_candidates = [
        workflow_path.parent.parent / "artifacts" / "heal_suggestions.json",
        workflow_path.parent / "artifacts" / "heal_suggestions.json",
    ]

    suggestions_path = None
    for p in report_candidates + legacy_candidates:
        if p.exists() and p.stat().st_size > 2:  # skip empty "[]" files
            suggestions_path = p
            break

    if suggestions_path is None:
        print("ERROR: no heal_suggestions.json found in reports/ or artifacts/.")
        return

    print(f"Using heal suggestions from: {suggestions_path}")

    suggestions: list[dict] = json.loads(suggestions_path.read_text(encoding="utf-8"))
    if not suggestions:
        print("Nothing to apply.")
        return

    raw = json.loads(workflow_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        steps = raw
    else:
        steps = raw.get("steps", [])

    patches: list[tuple[dict, dict, dict]] = []  # (step, original, healed)
    for suggestion in suggestions:
        desc     = suggestion.get("description", "")
        original = suggestion.get("original", {})
        healed   = suggestion.get("healed", {})
        matches  = [s for s in steps if s.get("description") == desc]
        if not matches:
            print(f"WARNING: no step found with description '{desc}' — skipping")
            continue
        if len(matches) > 1:
            print(f"WARNING: {len(matches)} steps match '{desc}' — patching all")
        for s in matches:
            patches.append((s, original, healed))

    if not patches:
        print("Nothing to apply.")
        return

    for i, (s, original, healed) in enumerate(patches, 1):
        print(f"Step {i} \"{s.get('description', '')}\":")
        print(f"  BEFORE: {json.dumps(original)}")
        print(f"  AFTER:  {json.dumps(healed)}")

    if not auto_yes:
        answer = input(f"Apply {len(patches)} heal(s) to {workflow_path}? [Y/n]: ").strip().lower()
        if answer == "n":
            print("Aborted.")
            return

    for step, _original, healed in patches:
        step["element"] = healed

    updated = raw if isinstance(raw, list) else {**raw, "steps": steps}
    workflow_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(patches)} heal(s) applied to {workflow_path}. Commit to make permanent.")


async def _run_data_rows(rows: list[dict], cli_vars: dict, args) -> None:
    """Open one playwright instance and browser; run each data row in a fresh context."""
    s        = load_settings_safe()
    resolver = build_resolver(s.use_visual_ai)

    async with async_playwright() as pw:
        browser = await launch_browser(pw, s.browser, not args.show, s.slow_mo)
        for i, row in enumerate(rows, 1):
            merged = {**row, **cli_vars}
            logger.info(f"[data-driven] row {i}/{len(rows)}: {merged}")
            await run(
                workflow_path=args.workflow,
                task=args.task,
                headless=not args.show,
                allure_serve=False,
                record_video=args.video,
                variables=merged,
                resolver=resolver,
                _browser=browser,
                shadow=args.shadow,
            )
        await browser.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    load_env()

    parser = argparse.ArgumentParser(description="Stepper — AI Browser Automation")
    parser.add_argument("--workflow",      help="Path to workflow JSON file")
    parser.add_argument("--task",          help="Natural language task description")
    parser.add_argument("--show",          action="store_true", help="Show browser window")
    parser.add_argument("--allure-serve",  action="store_true", help="Open Allure report in browser after run")
    parser.add_argument("--video",         action="store_true", help="Record video to test-*/videos/")
    parser.add_argument("--heal",          type=int, default=1, metavar="N",
                        help="Max self-healing attempts per failed step (default 1; pass 0 to disable)")
    parser.add_argument("--vars",          help='JSON string of variable overrides, e.g. \'{"query":"Foundation"}\'')
    parser.add_argument("--data",          help="Path to a JSON file containing an array of variable objects")
    parser.add_argument("--apply-heals",   metavar="WORKFLOW_JSON",
                        help="Apply heal_suggestions.json fixes to the given workflow file")
    parser.add_argument("--yes",           action="store_true",
                        help="Auto-confirm --apply-heals without interactive prompt")
    parser.add_argument("--shadow",        action="store_true",
                        help="Enable shadow mode — run all resolver strategies in background and log drift")
    parser.add_argument("--ci",            action="store_true",
                        help="Output structured JSON run summary to stdout (for CI/CD pipelines)")
    parser.add_argument("--ci-output",     metavar="FILE",
                        help="Write CI JSON summary to FILE in addition to stdout")
    args = parser.parse_args()

    if args.apply_heals:
        if args.workflow or args.task or args.data:
            parser.error("--apply-heals is mutually exclusive with --workflow, --task, and --data")
        apply_heals(Path(args.apply_heals), args.yes)
        return

    cli_vars: dict = {}
    if args.vars:
        try:
            cli_vars = json.loads(args.vars)
        except json.JSONDecodeError as e:
            parser.error(f"--vars is not valid JSON: {e}")

    if args.data:
        data_path = Path(args.data)
        if not data_path.exists():
            parser.error(f"--data file not found: {data_path}")
        rows: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            parser.error("--data file must contain a JSON array of objects")
        asyncio.run(_run_data_rows(rows, cli_vars, args))
        if args.allure_serve:
            serve_allure(_stepper_root)
        return

    asyncio.run(run(
        workflow_path=args.workflow,
        task=args.task,
        headless=not args.show,
        allure_serve=args.allure_serve,
        record_video=args.video,
        variables=cli_vars or None,
        max_heal_attempts=args.heal,
        shadow=args.shadow,
        ci=args.ci,
        ci_output=args.ci_output,
    ))


if __name__ == "__main__":
    main()
