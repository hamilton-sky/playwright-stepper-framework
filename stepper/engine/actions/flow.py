"""
actions/flow.py — actions that run other actions.

Everything here dispatches sub-steps through the ActionFactory it was
constructed with: loop over a collection, log in if not already, walk
paginated results, fan out across browser contexts, call another workflow.

These are the only actions that take an `action_factory` at construction, which
is why the registry builds them by hand in factory.py rather than with a bare
constructor call.

Retry, continue_on_failure and healing are NOT here — those belong to
StepRunner. Sub-step dispatch is; it goes through SubStepRunnerMixin, which may
pass behaviour=None, so every _execute below keeps its default.
"""

from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
)
from stepper.engine.utils import dict_to_step_config as _dict_to_step_config
from stepper.engine.actions.sub_step_mixin import SubStepRunnerMixin

logger = logging.getLogger(__name__)


class ForEachItemAction(SubStepRunnerMixin, ActionStrategy):
    """
    Iterate over collected item URLs and run sub-steps on each.
    Template variables: {{item_url}}, {{book_url}} (compat), {{index}}
    Metadata (dict items): {{item.<key>}} for any key in the item dict
    """
    action_name = "for_each_item"

    def __init__(self, action_factory, screenshots_dir: Path = Path("artifacts/screenshots")):
        self._factory = action_factory
        self._screenshots_dir = screenshots_dir

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        # Prefer typed context field; fall back to legacy page attribute
        items = (
            context.collected_items
            or getattr(page, "_collected_items", [])
            or getattr(page, "_collected_books", [])
        )
        sub_steps_raw = step.extra.get("steps", [])

        for idx, item in enumerate(items):
            if isinstance(item, dict):
                item_url = (
                    item.get("url")
                    or item.get("href")
                    or item.get("link")
                    or ""
                )
            else:
                item_url = item

            subs = {
                "item_url": str(item_url),
                "book_url": str(item_url),  # backward compatibility
                "index": str(idx + 1),
            }
            if isinstance(item, dict):
                for key, val in item.items():
                    subs[f"item.{key}"] = val

            try:
                await self._run_sub_steps(
                    sub_steps_raw, page, resolver, context,
                    substitutions=subs,
                    stop_on_failure=False,
                    behaviour=behaviour,
                )
            except Exception as e:
                logger.error(f"ForEach item {idx+1}: {e}")
                await page.screenshot(
                    path=str(self._screenshots_dir / f"error_book_{idx+1}.png")
                )

        return StepResult(step=step, status="passed")


class EnsureLoginAction(SubStepRunnerMixin, ActionStrategy):
    """
    Ensure the user is logged in before continuing.

    Expected step.extra:
      login_steps: list[dict]   # steps to perform login if needed
      check_url: str            # url to navigate for login check (optional)
      login_url_fragment: str   # substring indicating login page (optional)
      logged_in_selector: str   # selector to confirm logged-in state (optional)
    """
    action_name = "ensure_login"

    def __init__(self, action_factory):
        self._factory = action_factory

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        login_steps = step.extra.get("login_steps", [])
        check_url = step.extra.get("check_url")
        login_url_fragment = step.extra.get("login_url_fragment", "/account/login")
        logged_in_selector = step.extra.get("logged_in_selector")

        if check_url:
            try:
                await page.goto(check_url, wait_until="networkidle", timeout=30_000)
            except Exception as e:
                logger.warning(
                    "ensure_login: protected page networkidle navigation failed (%s), retrying domcontentloaded",
                    e,
                )
                await page.goto(check_url, wait_until="domcontentloaded", timeout=30_000)

        if login_url_fragment and login_url_fragment in page.url:
            logged_in = False
        elif logged_in_selector:
            try:
                logged_in = await page.locator(logged_in_selector).count() > 0
            except Exception:
                logged_in = False
        else:
            logged_in = False

        if logged_in:
            logger.info("✓ ensure_login: already logged in")
            return StepResult(step=step, status="passed")

        if not login_steps:
            return StepResult(
                step=step,
                status="failed",
                error="ensure_login: missing extra.login_steps",
            )

        logger.info("→ ensure_login: running login steps")
        # Wait for the login form to be ready before filling credentials
        ready_selector = step.extra.get("form_ready_selector")
        if ready_selector:
            try:
                await page.wait_for_selector(ready_selector, state="visible", timeout=10_000)
            except Exception:
                pass

        try:
            results = await self._run_sub_steps(
                login_steps, page, resolver, context,
                stop_on_failure=True,
                behaviour=behaviour,
            )
        except Exception as e:
            logger.error("ensure_login step failed: %s", e)
            return StepResult(step=step, status="failed", error=str(e))

        for result in results:
            if result.status != "passed":
                return StepResult(
                    step=step,
                    status="failed",
                    error=f"ensure_login: step '{result.step.description or result.step.action}' {result.status}",
                )

        if check_url:
            await page.goto(check_url, wait_until="domcontentloaded", timeout=30_000)

        return StepResult(step=step, status="passed")


class PaginateAction(ActionStrategy):
    """
    Paginate through results and extract data from each page.
    
    Uses ExtractDataAction internally to extract data from each page.
    Accumulates all results and stores in context.
    
    Step config expected:
        action: "paginate"
        extra:
            extract_config:  # passed to ExtractDataAction
                selector: "CSS selector"
                attrs: ["href"]
            next_button_selector: "CSS selector for next button"  (optional)
            next_url_pattern: "/search?page={{page_num}}"  (optional — template-based)
            max_pages: 5  (optional)
            max_items: 50  (optional)
    
    Stores result in context["paginated_data"] = [accumulated values]
    """
    action_name = "paginate"

    def __init__(self, action_factory):
        self._factory = action_factory

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        try:
            extract_config = step.extra.get("extract_config")
            if not extract_config or "selector" not in extract_config:
                return StepResult(
                    step=step,
                    status="failed",
                    error="Missing required field: extra.extract_config.selector"
                )
            
            next_button_selector = step.extra.get("next_button_selector")
            next_url_pattern = step.extra.get("next_url_pattern")
            max_pages = step.extra.get("max_pages", 10)
            max_items = step.extra.get("max_items", 1000)
            
            if not next_button_selector and not next_url_pattern:
                return StepResult(
                    step=step,
                    status="failed",
                    error="Must provide either next_button_selector or next_url_pattern"
                )
            
            accumulated: list = []
            page_num = 1
            
            while len(accumulated) < max_items and page_num <= max_pages:
                # Extract data from current page
                extract_step = StepConfig(
                    action="extract_data",
                    description=f"Extract page {page_num}",
                    extra={
                        **extract_config,
                        "limit": min(extract_config.get("limit", max_items), 
                                    max_items - len(accumulated))
                    }
                )
                
                action = self._factory.create("extract_data")
                extract_result = await action.execute(
                    page, extract_step, resolver, context, behaviour
                )
                
                if extract_result.status == "passed" and context.extracted_data:
                    accumulated.extend(context.extracted_data)
                    logger.info(f"  page {page_num}: +{len(context.extracted_data)} items")
                
                if len(accumulated) >= max_items:
                    break
                
                # Navigate to next page
                has_next = False
                
                if next_url_pattern:
                    # URL-based pagination
                    page_num += 1
                    next_url = next_url_pattern.replace("{{page_num}}", str(page_num))
                    current_url = page.url
                    next_full_url = next_url if next_url.startswith("http") else \
                                   current_url.rsplit("/", 1)[0] + next_url
                    try:
                        await page.goto(next_full_url, wait_until="domcontentloaded", timeout=15_000)
                        has_next = True
                    except Exception as e:
                        logger.debug(f"  no more pages (URL): {e}")
                        has_next = False
                
                elif next_button_selector:
                    # Button-based pagination
                    try:
                        next_btn = page.locator(next_button_selector)
                        is_enabled = await next_btn.is_enabled()
                        is_visible = await next_btn.is_visible()
                        
                        if is_enabled and is_visible:
                            await next_btn.click()
                            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                            page_num += 1
                            has_next = True
                        else:
                            logger.debug("  next button disabled or hidden")
                    except Exception as e:
                        logger.debug(f"  no more pages (button): {e}")
                
                if not has_next:
                    break
            
            context.paginated_data = accumulated
            logger.info(f"✓ paginate: {len(accumulated)} items across {page_num} page(s)")
            
            return StepResult(
                step=step,
                status="passed",
            )
        
        except Exception as e:
            return StepResult(
                step=step,
                status="failed",
                error=f"paginate: {str(e)}"
            )


class ParallelAction(ActionStrategy):
    """
    Run multiple read-only sub-steps concurrently.

    Modes (extra.mode):
      "tabs"             — one new page per sub-step, shared browser context
                           (same session, fastest, default)
      "isolated_browser" — one new browser instance per sub-step, each loads
                           storage_state.json for auth (full isolation)

    Safety gate: ALL sub-steps must be read_only=True actions.
    If any sub-step is a write action, the whole parallel step fails immediately
    without executing anything.

    JSON usage:
      {
        "action": "parallel",
        "extra": {
          "mode": "tabs",
          "steps": [
            { "action": "screenshot", "name": "page_a" },
            { "action": "extract_data", "selector": "h1", "attrs": ["innerText"] }
          ]
        }
      }

    Results: all sub-step results are collected; parallel step passes only if
    ALL sub-steps pass. First failure is reported as the parallel step error.
    """
    action_name = "parallel"
    read_only   = True   # parallel itself is read-only (enforces it on children)

    def __init__(self, action_factory, browser_launcher=None):
        self._factory = action_factory
        self._launcher = browser_launcher

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        sub_steps_raw = step.extra.get("steps", [])
        mode          = step.extra.get("mode", "tabs")

        if not sub_steps_raw:
            return StepResult(step=step, status="skipped",
                              error="parallel: no sub-steps defined")

        sub_steps = [_dict_to_step_config(s) for s in sub_steps_raw]

        # ── Safety gate — refuse write actions ───────────────────────────────
        write_actions = []
        for s in sub_steps:
            try:
                action = self._factory.create(s.action)
                if not action.read_only:
                    write_actions.append(s.action)
            except ValueError:
                write_actions.append(f"{s.action} (unknown)")

        if write_actions:
            return StepResult(
                step=step, status="failed",
                error=(
                    f"parallel: write actions not allowed in parallel mode: "
                    f"{write_actions}. Only read_only=True actions are permitted."
                )
            )

        # ── Execute in parallel ───────────────────────────────────────────────
        try:
            if mode == "isolated_browser":
                if self._launcher is None:
                    return StepResult(
                        step=step, status="failed",
                        error="parallel isolated_browser mode requires a browser_launcher — none was injected",
                    )
                results = await self._run_isolated_browsers(sub_steps, resolver, context, behaviour)
            else:
                results = await self._run_tabs(page, sub_steps, resolver, context, behaviour)
        except Exception as e:
            logger.error(f"parallel execution error: {e}")
            return StepResult(step=step, status="failed", error=str(e))

        # ── Aggregate results ─────────────────────────────────────────────────
        failures = [r for r in results if r.status == "failed"]
        if failures:
            errors = "; ".join(r.error for r in failures if r.error)
            return StepResult(step=step, status="failed", error=errors)

        logger.info(f"parallel: {len(results)}/{len(results)} sub-steps passed ({mode})")
        return StepResult(step=step, status="passed")

    async def _run_tabs(self, page, sub_steps: list[StepConfig],
                        resolver, context: ExecutionContext,
                        behaviour=None) -> list[StepResult]:
        """Spawn one new tab per sub-step in the same browser context."""
        browser_context = page.context

        async def run_one(sub_step: StepConfig) -> StepResult:
            tab = await browser_context.new_page()
            try:
                action = self._factory.create(sub_step.action)
                return await action.execute(tab, sub_step, resolver, context, behaviour)
            except Exception as e:
                return StepResult(step=sub_step, status="failed", error=str(e))
            finally:
                await tab.close()

        return list(await asyncio.gather(*[run_one(s) for s in sub_steps]))

    async def _run_isolated_browsers(self, sub_steps: list[StepConfig],
                                     resolver, context: ExecutionContext,
                                     behaviour=None) -> list[StepResult]:
        """Spawn one isolated browser per sub-step via the injected IBrowserLauncher."""
        async def run_one(sub_step: StepConfig) -> StepResult:
            handle, tab = await self._launcher.create_page()
            try:
                action = self._factory.create(sub_step.action)
                return await action.execute(tab, sub_step, resolver, context, behaviour)
            except Exception as e:
                return StepResult(step=sub_step, status="failed", error=str(e))
            finally:
                await self._launcher.release(handle)

        return list(await asyncio.gather(*[run_one(s) for s in sub_steps]))


class RunWorkflowAction(ActionStrategy):
    """
    Execute a sub-workflow JSON file at runtime, then return to the parent flow.

    Expected step.extra:
      path: str        # path to workflow JSON file (relative or absolute)
      vars: dict       # optional variable overrides for this subflow
      base_dir: str    # optional base dir for relative paths
    """
    action_name = "run_workflow"

    def __init__(self, run_steps_callable=None, base_dir: Path | None = None):
        self._run_steps = run_steps_callable
        self._base_dir = base_dir or Path.cwd()

    def bind(self, run_steps_callable):
        """
        Attach the runner's run() after construction.

        A plan can only be validated once every action it names is registered,
        but the runner cannot exist before its page does. Registering this
        action unbound and binding it here breaks that cycle, so validation
        happens before a browser is launched.
        """
        self._run_steps = run_steps_callable
        return self

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        from stepper.engine.planner.planner import _substitute

        if self._run_steps is None:
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: action was registered but never bound to a runner",
            )

        wf_path = (step.extra or {}).get("path") or (step.extra or {}).get("workflow")
        if not wf_path:
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: missing extra.path",
            )

        base_dir = self._base_dir
        if (step.extra or {}).get("base_dir"):
            base_dir = Path(step.extra["base_dir"])

        wf_path = Path(wf_path)
        if not wf_path.is_absolute():
            wf_path = (base_dir / wf_path).resolve()

        if not wf_path.exists():
            return StepResult(
                step=step,
                status="failed",
                error=f"run_workflow: file not found: {wf_path}",
            )

        with open(wf_path, encoding="utf-8") as f:
            data = json.load(f)

        steps_raw = data.get("steps", data) if isinstance(data, dict) else data
        if not isinstance(steps_raw, list):
            return StepResult(
                step=step,
                status="failed",
                error="run_workflow: workflow JSON must be a list or {steps:[...]}",
            )

        merged_vars = {
            **(data.get("variables", {}) if isinstance(data, dict) else {}),
            **((step.extra or {}).get("vars") or {}),
        }
        if merged_vars:
            steps_raw = _substitute(steps_raw, merged_vars)

        sub_steps = [_dict_to_step_config(s) for s in steps_raw]

        results, _ = await self._run_steps(sub_steps, context)
        failures = [r for r in results if r.status == "failed"]
        if failures:
            msg = failures[0].error or "subflow failed"
            return StepResult(step=step, status="failed", error=msg)

        return StepResult(step=step, status="passed")
