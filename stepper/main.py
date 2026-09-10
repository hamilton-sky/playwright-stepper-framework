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
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# Let `python stepper/main.py` work straight from a checkout, before anyone has
# run `pip install -e .`. Python puts stepper/ on the path for us as the script
# directory; the repo root is what `poms` needs. Both are redundant once the
# package is installed, and harmless when it is.
# (A third entry pointed at stepper/src/, which has never existed.)
_root_path   = str(Path(__file__).parent)
_parent_path = str(Path(__file__).parent.parent)
for _p in (_parent_path, _root_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bootstrap.settings  import load_env, load_settings_safe
from bootstrap.infra     import build_resolver, launch_browser, register_all_sites
from bootstrap.reporting import build_reporters, serve_allure

from engine.browser.anti_detection import AntiDetection
from engine.actions.factory      import build_default_registry
from engine.planner.validator    import PlanValidator
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


#: Sites that persist a logged-in session across runs. Others log in fresh.
_SITES_WITH_PERSISTENCE = {"openlibrary"}

#: Actions whose success means there is a session worth saving.
_LOGIN_ACTIONS = {"ol_ensure_login", "sd_login", "ensure_login"}


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


# ──────────────────────────────────────────────────────────────────────────────
# RUN CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunConfig:
    """
    Everything one run needs to know, as a single value object.

    Replaces the twelve keyword arguments that used to thread through run(), and
    owns the derivations (site name, artifact paths, run label) that were
    previously recomputed inline at four separate points.
    """

    workflow_path: str | None = None
    task: str | None = None
    headless: bool = True
    allure_serve: bool = False
    record_video: bool = False
    variables: dict | None = None
    max_heal_attempts: int = 0
    shadow: bool = False
    ci: bool = False
    ci_output: str | None = None

    def __post_init__(self) -> None:
        if not self.workflow_path and not self.task:
            raise ValueError("Provide --workflow or --task")

    @property
    def site(self) -> str:
        """Site directory name, derived from the workflow path ('shared' for --task)."""
        return _extract_site(self.workflow_path)

    @property
    def run_label(self) -> str:
        return Path(self.workflow_path).stem if self.workflow_path else "task"

    @property
    def suite_name(self) -> str:
        return self.workflow_path or self.task or "automation"

    @property
    def base_dir(self) -> Path:
        """Directory that relative run_workflow paths resolve against."""
        return Path(self.workflow_path).parent if self.workflow_path else Path.cwd()

    def artifact_path(self, filename: str) -> Path:
        """Path inside this run's own site artifacts directory."""
        return _stepper_root / "sites" / self.site / "artifacts" / filename

    @property
    def storage_state_path(self) -> Path | None:
        """
        Where this site's logged-in session is persisted, or None.

        Only OpenLibrary needs saved sessions; SauceDemo and phpTravels log in
        fresh each run.
        """
        return (
            self.artifact_path("storage_state.json")
            if self.site in _SITES_WITH_PERSISTENCE
            else None
        )


@dataclass
class PreparedRun:
    """
    A planned, validated run — everything assembled that does not need a browser.

    Building this is cheap and side-effect-free apart from creating the report
    directories, so a caller can validate a workflow without paying for a
    browser launch.
    """

    cfg: RunConfig
    steps: list
    settings: Any
    resolver: Any
    reporter: Any
    test_reporter: Any
    registry: Any
    screenshots_dir: Path
    subflow_action: RunWorkflowAction


@dataclass
class Pipeline:
    """A prepared run bound to a live page — ready to execute, not yet executed."""

    prepared: PreparedRun
    runner: StepRunner
    context: Any
    page: Any

    @property
    def cfg(self) -> RunConfig:
        return self.prepared.cfg

    @property
    def steps(self) -> list:
        return self.prepared.steps


# ──────────────────────────────────────────────────────────────────────────────
# ASSEMBLY — each step of what used to be run()'s opening 100 lines
# ──────────────────────────────────────────────────────────────────────────────

def plan_steps(cfg: RunConfig) -> list:
    """Turn a workflow file or a natural-language task into StepConfigs."""
    if cfg.workflow_path:
        from engine.planner.planner import JsonFilePlanner
        planner = JsonFilePlanner(cfg.workflow_path, variables=cfg.variables)
    else:
        from engine.planner.planner import ClaudePlanner
        planner = ClaudePlanner()

    steps = planner.plan(cfg.task or "")
    logger.info(f"Planned {len(steps)} steps")
    return steps


def build_settings(cfg: RunConfig):
    """Load this run's own site's settings, and point storage state at it."""
    return load_settings_safe(cfg.site)._replace(storage_state_path=cfg.storage_state_path)


def wrap_for_shadow(cfg: RunConfig, resolver):
    """Wrap a resolver so every strategy also runs in the background, logging drift."""
    from engine.resolvers.shadow_runner import ShadowRunner, DriftLog
    from engine.resolvers.element_resolver import DefaultResolverFactory

    drift_path = cfg.artifact_path("drift_log.json")
    logger.info("👁  Shadow mode enabled — drift log → %s", drift_path)
    return ShadowRunner(resolver, DefaultResolverFactory().build_cascade(), DriftLog(drift_path))


def resolve_screenshots_dir(cfg: RunConfig, test_reporter) -> Path:
    """
    Where auto-screenshots land: the per-test report dir, else the site's own
    artifacts folder.

    The fallback used to be hardcoded to openlibrary, so a SauceDemo run without
    a test reporter wrote its screenshots into another site's directory.
    """
    if test_reporter and test_reporter.manager.current_test_dir:
        return test_reporter.manager.get_screenshots_dir()
    return cfg.artifact_path("screenshots")


def build_action_registry(cfg: RunConfig, settings, screenshots_dir: Path):
    """Engine actions plus every site's glue actions."""
    from poms.shared.driver import PlaywrightBrowserLauncher

    launcher = PlaywrightBrowserLauncher(
        headless=cfg.headless,
        storage_state_path=(
            Path(str(settings.storage_state_path)) if settings.storage_state_path else None
        ),
    )
    registry = build_default_registry(
        screenshots_dir=screenshots_dir,
        browser_launcher=launcher,
    )
    register_all_sites(registry, _stepper_root, screenshots_dir=screenshots_dir)
    return registry


def build_healer(cfg: RunConfig, registry):
    """An AiHealer when healing was asked for and a provider key exists, else None."""
    if cfg.max_heal_attempts <= 0:
        return None

    if not any(os.getenv(k) for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")):
        logger.warning("⚕ --heal requested but no LLM API key found — healing disabled")
        return None

    from engine.ai.service import AIService
    from engine.healer.ai_healer import AiHealer
    from engine.planner.schema_extractor import ActionSchemaExtractor

    logger.info(f"⚕ Self-healing enabled (max {cfg.max_heal_attempts} attempt(s) per step)")
    return AiHealer(
        action_schema=ActionSchemaExtractor.extract(registry),
        ai_service=AIService(),
    )


def build_validated_registry(cfg: RunConfig, settings, screenshots_dir: Path, steps):
    """
    Build the complete action registry and check the plan against it.

    Shared by prepare_run and validate_plan so a workflow that passes `validate`
    cannot be rejected at run time by a differently-built registry.
    """
    registry = build_action_registry(cfg, settings, screenshots_dir)

    # Registered unbound: run_workflow needs the runner, which needs a page.
    # Binding is deferred so the plan can be validated before a browser exists.
    subflow_action = RunWorkflowAction(base_dir=cfg.base_dir)
    registry.register(subflow_action)

    PlanValidator.validate(steps, registry)
    return registry, subflow_action


def validate_plan(cfg: RunConfig, settings=None) -> list:
    """
    Plan and validate with no browser, no reporters and no directories created.

    Pass `settings` when validating many workflows in a row — loading them is
    what emits the provider-key warnings, and once is enough.

    Raises PlanValidationError when the plan is bad; returns the steps when good.
    """
    steps = plan_steps(cfg)
    build_validated_registry(
        cfg,
        settings if settings is not None else build_settings(cfg),
        cfg.artifact_path("screenshots"),
        steps,
    )
    return steps


def prepare_run(cfg: RunConfig, resolver=None) -> PreparedRun:
    """
    Plan and validate a run without launching a browser.

    Everything here is browser-free, so an invalid workflow is rejected before
    any expensive resource is opened — and a caller that only wants to check a
    plan can stop after this call.
    """
    steps    = plan_steps(cfg)
    settings = build_settings(cfg)

    if resolver is None:
        resolver = build_resolver(settings.use_visual_ai)
    if cfg.shadow:
        resolver = wrap_for_shadow(cfg, resolver)

    reporter, test_reporter = build_reporters(
        cfg.run_label, settings.browser, cfg.headless, _stepper_root
    )

    screenshots_dir = resolve_screenshots_dir(cfg, test_reporter)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    registry, subflow_action = build_validated_registry(
        cfg, settings, screenshots_dir, steps
    )

    return PreparedRun(
        cfg=cfg, steps=steps, settings=settings, resolver=resolver,
        reporter=reporter, test_reporter=test_reporter, registry=registry,
        screenshots_dir=screenshots_dir, subflow_action=subflow_action,
    )


async def open_page(cfg: RunConfig, browser, settings, test_reporter):
    """Create the browser context and page, with session, video and stealth applied."""
    context_kwargs: dict = {"viewport": {"width": 1280, "height": 800}}
    context_kwargs.update(AntiDetection.context_kwargs())

    if settings.storage_state_path and Path(str(settings.storage_state_path)).exists():
        context_kwargs["storage_state"] = str(settings.storage_state_path)
        logger.info(f"Loaded session from {settings.storage_state_path}")

    if cfg.record_video and test_reporter and test_reporter.manager.current_test_dir:
        videos_dir = test_reporter.manager.current_test_dir / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        context_kwargs["record_video_dir"]  = str(videos_dir)
        context_kwargs["record_video_size"] = {"width": 1280, "height": 800}
        logger.info(f"Recording video → {videos_dir}")

    context = await browser.new_context(**context_kwargs)
    page    = await context.new_page()
    await AntiDetection.apply_page_patches(page)
    return context, page


async def build_pipeline(prepared: PreparedRun, browser, observers=None) -> Pipeline:
    """
    Bind a prepared run to a live page.

    Split out of run() so callers that are not the CLI — a test, a server, a UI —
    can hold the runner and page and drive them directly. `observers` are added
    alongside the default LoggingObserver, which is how a UI streams step events.
    """
    cfg = prepared.cfg
    context, page = await open_page(cfg, browser, prepared.settings, prepared.test_reporter)

    heal_cache = None
    if cfg.workflow_path:
        from engine.healer.healing_cache import HealCache
        heal_cache = HealCache(cfg.artifact_path("heal_cache.json"))

    runner = StepRunner(
        page=page,
        action_factory=prepared.registry,
        resolver=prepared.resolver,
        reporter=prepared.reporter,
        screenshots_dir=prepared.screenshots_dir,
        healer=build_healer(cfg, prepared.registry),
        max_heal_attempts=cfg.max_heal_attempts,
        cache=heal_cache,
    )
    runner.add_observer(LoggingObserver())
    for observer in observers or ():
        runner.add_observer(observer)

    prepared.subflow_action.bind(runner.run)

    return Pipeline(prepared=prepared, runner=runner, context=context, page=page)


# ──────────────────────────────────────────────────────────────────────────────
# EXECUTION
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def _tee_logs_to_run_file(test_reporter):
    """Mirror DEBUG-level logging into the per-test run.log for the duration."""
    handler = None
    if test_reporter and test_reporter.manager.current_test_dir:
        log_path = test_reporter.manager.current_test_dir / "logs" / "run.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)   # file gets DEBUG; console stays INFO
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S"
        ))
        logging.getLogger().addHandler(handler)
    try:
        yield
    finally:
        # Previously only removed on the happy path, so a failing run leaked the
        # handler and every later run wrote into the first run's log file.
        if handler:
            logging.getLogger().removeHandler(handler)
            handler.close()


def _write_ci_summary(cfg: RunConfig, results, resolver, duration_s: float) -> None:
    summary = _build_ci_summary(results, cfg.workflow_path, resolver, duration_s)
    print(json.dumps(summary, indent=2))
    if cfg.ci_output:
        # Create the parent dir first: on a failing run nothing else has
        # written to reports/ yet, and a FileNotFoundError here would
        # discard the very summary that explains the failure.
        out_path = Path(cfg.ci_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info(f"CI summary written to {cfg.ci_output}")


async def _save_session_if_logged_in(cfg: RunConfig, settings, context, results) -> None:
    if not settings.storage_state_path:
        return
    if not any(r.step.action in _LOGIN_ACTIONS for r in results):
        logger.debug("Skipping storage_state write — no login action ran")
        return
    Path(str(settings.storage_state_path)).parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(settings.storage_state_path))
    logger.info(f"Session saved to {settings.storage_state_path}")


async def execute_pipeline(pipeline: Pipeline) -> list:
    """Run the planned steps and write out everything the run produced."""
    cfg      = pipeline.cfg
    prepared = pipeline.prepared

    prepared.reporter.start_suite(cfg.suite_name)

    started = time.monotonic()
    results, _ = await pipeline.runner.run(pipeline.steps)
    duration_s = time.monotonic() - started

    prepared.reporter.finish_suite()

    if cfg.ci:
        _write_ci_summary(cfg, results, prepared.resolver, duration_s)

    drift_log = getattr(prepared.resolver, "_drift_log", None)
    if cfg.shadow and drift_log is not None:
        drift_log.flush()

    await _save_session_if_logged_in(cfg, prepared.settings, pipeline.context, results)
    return results


async def run(
    workflow_path: str | None = None,
    task: str | None = None,
    headless: bool = True,
    allure_serve: bool = False,
    record_video: bool = False,
    variables: dict | None = None,
    resolver=None,
    max_heal_attempts: int = 0,
    shadow: bool = False,
    ci: bool = False,
    ci_output: str | None = None,
    observers=None,
):
    """
    Plan, assemble and execute one run — the whole pipeline end to end.

    Launches its own browser and closes it. Callers needing finer control — a
    shared browser, step-event streaming, validation without a browser — use the
    pieces directly:

        steps    = validate_plan(cfg)               # no browser at all
        prepared = prepare_run(cfg)
        pipeline = await build_pipeline(prepared, browser, observers=[my_observer])
        results  = await execute_pipeline(pipeline)
    """
    cfg = RunConfig(
        workflow_path=workflow_path,
        task=task,
        headless=headless,
        allure_serve=allure_serve,
        record_video=record_video,
        variables=variables,
        max_heal_attempts=max_heal_attempts,
        shadow=shadow,
        ci=ci,
        ci_output=ci_output,
    )

    # Plan and validate before anything expensive is opened.
    prepared = prepare_run(cfg, resolver=resolver)

    async_playwright = AntiDetection.get_playwright()
    pw_instance = await async_playwright().start()
    browser = await launch_browser(pw_instance, prepared.settings.browser,
                                   cfg.headless, prepared.settings.slow_mo)

    try:
        with _tee_logs_to_run_file(prepared.test_reporter):
            pipeline = await build_pipeline(prepared, browser, observers=observers)
            try:
                results = await execute_pipeline(pipeline)
            finally:
                # Closing the context flushes any recorded video, so it has to
                # happen even when the run raised.
                await pipeline.context.close()
    finally:
        await browser.close()
        await pw_instance.stop()

    if cfg.allure_serve:
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


async def run_data_rows(cfg: RunConfig, rows: list[dict], cli_vars: dict) -> None:
    """
    Run one workflow once per data row, reusing a single browser.

    Each row gets its own context and its own report directory; the browser and
    the resolver are built once for the whole set.
    """
    settings = build_settings(cfg)
    resolver = build_resolver(settings.use_visual_ai)

    async_playwright = AntiDetection.get_playwright()
    async with async_playwright() as pw:
        browser = await launch_browser(pw, settings.browser, cfg.headless, settings.slow_mo)
        try:
            for i, row in enumerate(rows, 1):
                merged = {**row, **cli_vars}
                logger.info(f"[data-driven] row {i}/{len(rows)}: {merged}")

                row_cfg  = replace(cfg, variables=merged, allure_serve=False)
                prepared = prepare_run(row_cfg, resolver=resolver)
                with _tee_logs_to_run_file(prepared.test_reporter):
                    pipeline = await build_pipeline(prepared, browser)
                    try:
                        await execute_pipeline(pipeline)
                    finally:
                        await pipeline.context.close()
        finally:
            await browser.close()


def main() -> None:
    """Entry point — the CLI itself lives in cli.py, this module is the pipeline."""
    import cli
    raise SystemExit(cli.run_cli(sys.modules[__name__]))


if __name__ == "__main__":
    main()
