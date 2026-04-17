"""
actions/strategies.py — Concrete ActionStrategy implementations.

Pattern: Strategy + Template Method
  Each action class handles ONE action type.
  Base class (ActionStrategy) owns the execute() skeleton.
  Subclasses override _execute() only.

SRP: NavigateAction only navigates. ClickAction only clicks. Etc.
OCP: Add FillFormAction, HoverAction, DragAction — zero changes elsewhere.
"""

from __future__ import annotations
import asyncio
import copy
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# Absolute path to stepper/ — used to resolve relative output paths in workflow
# JSON files so files always land inside stepper/ regardless of cwd.
_stepper_root = Path(__file__).resolve().parent.parent.parent  # stepper/stepper/actions/ → stepper/

from engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
    CONFIDENCE_AUTO, CONFIDENCE_WARN,
)
from engine.utils import dict_to_step_config as _dict_to_step_config
from engine.actions.sub_step_mixin import SubStepRunnerMixin, _apply_substitutions

logger = logging.getLogger(__name__)

# Confidence gate constants imported from engine.interfaces (single source of truth)


# ──────────────────────────────────────────────────────────
# PHASE 1 — Basic actions (exam requirements)
# ──────────────────────────────────────────────────────────

class NavigateAction(ActionStrategy):
    """
    Navigate to a URL and wait for the page to load.
    Handles both absolute URLs and relative paths.
    """
    action_name = "navigate"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        url = step.input_value or step.url
        if not url.startswith("http"):
            url = f"https://{url}"

        logger.info(f"→ navigate: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        if step.wait_for:
            await _wait_for(page, step.wait_for)

        return StepResult(step=step, status="passed")


class ClickAction(ActionStrategy):
    """
    Find an element via the cascade resolver and click it.
    Applies the confidence gate before acting.
    """
    action_name = "click"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        _, err = _checked_input_value(step)
        if err:
            return err
        result = await resolver.resolve(page, step.element, step.description)

        if not result.found:
            return StepResult(step=step, status="skipped",
                              error=f"Element not found → {result.method}")

        if result.confidence < CONFIDENCE_WARN:
            return StepResult(step=step, status="warned",
                              confidence=result.confidence,
                              error=f"Low confidence {result.confidence:.0%} → skipped")

        if result.confidence < CONFIDENCE_AUTO:
            logger.warning(f"Medium confidence {result.confidence:.0%} → attempting")

        force = step.extra.get("force", False) if step.extra else False
        js_click = step.extra.get("js_click", False) if step.extra else False

        if js_click:
            # JavaScript click bypasses all Playwright actionability checks,
            # including display:none — needed for hidden dropdown buttons.
            await result.locator.first.evaluate("el => el.click()")
            logger.info(f"✓ js_click via {result.method} ({result.confidence:.0%})")
        else:
            if not force:
                await result.locator.scroll_into_view_if_needed()
            await result.locator.click(timeout=5_000, force=force)
            logger.info(f"✓ click via {result.method} ({result.confidence:.0%})")

        if step.wait_for:
            await _wait_for(page, step.wait_for)

        return StepResult(step=step, status="passed", confidence=result.confidence)


class FillAction(ActionStrategy):
    """
    Find an input element and type a value into it.
    Presses Enter after filling to submit if no wait_for is specified.
    """
    action_name = "fill"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        value, err = _checked_input_value(step)
        if err:
            return err

        result = await resolver.resolve(page, step.element, step.description)

        if not result.found:
            return StepResult(step=step, status="skipped",
                              error=f"Element not found → {result.method}")

        await result.locator.scroll_into_view_if_needed()
        await result.locator.fill(value, timeout=5_000)
        if step.extra.get("press_enter", True):
            await result.locator.press("Enter")
        logger.info(f"✓ fill '{value}' via {result.method}")

        if step.wait_for:
            await _wait_for(page, step.wait_for)

        return StepResult(step=step, status="passed", confidence=result.confidence)


class HoverAction(ActionStrategy):
    """
    Hover over an element (triggers CSS :hover, opens hover menus).
    read_only because hover produces no side-effects on its own.
    """
    action_name = "hover"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        result = await resolver.resolve(page, step.element, step.description)

        if not result.found:
            return StepResult(step=step, status="skipped",
                              error=f"Element not found → {result.method}")

        await result.locator.first.hover(timeout=5_000)
        logger.info(f"✓ hover via {result.method} ({result.confidence:.0%})")

        if step.wait_for:
            await _wait_for(page, step.wait_for)

        return StepResult(step=step, status="passed", confidence=result.confidence)


class SelectAction(ActionStrategy):
    """
    Select an option from a <select> dropdown.

    Resolution priority for the option to select (checked in order):
      1. extra.label  — visible option text  e.g. "United States"
      2. extra.index  — 0-based integer index
      3. input_value  — option value attribute  e.g. "us"

    JSON usage:
      { "action": "select",
        "element": { "label": "Country" },
        "input_value": "us" }

      { "action": "select",
        "element": { "css": "#sort-order" },
        "extra": { "label": "Newest first" } }
    """
    action_name = "select"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        result = await resolver.resolve(page, step.element, step.description)

        if not result.found:
            return StepResult(step=step, status="skipped",
                              error=f"Element not found → {result.method}")

        label = step.extra.get("label")
        index = step.extra.get("index")
        value = step.input_value or ""

        try:
            if label is not None:
                await result.locator.first.select_option(label=str(label), timeout=5_000)
                chosen = f"label={label!r}"
            elif index is not None:
                await result.locator.first.select_option(index=int(index), timeout=5_000)
                chosen = f"index={index}"
            else:
                await result.locator.first.select_option(value=value, timeout=5_000)
                chosen = f"value={value!r}"
        except Exception as e:
            return StepResult(step=step, status="failed", error=str(e))

        logger.info(f"✓ select {chosen} via {result.method} ({result.confidence:.0%})")

        if step.wait_for:
            await _wait_for(page, step.wait_for)

        return StepResult(step=step, status="passed", confidence=result.confidence)


class ScreenshotAction(ActionStrategy):
    """Take a screenshot and save it to screenshots/."""
    action_name = "screenshot"
    read_only   = True

    def __init__(self, screenshots_dir: Path = Path("artifacts/screenshots")):
        self._screenshots_dir = screenshots_dir

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        ts   = datetime.now().strftime("%H%M%S")
        name = step.extra.get("filename") or f"{ts}_step.png"
        path = str(self._screenshots_dir / name)
        await page.screenshot(path=path, full_page=False)
        logger.info(f"📸 screenshot: {path}")
        return StepResult(step=step, status="passed", screenshot=path)


class WaitAction(ActionStrategy):
    """Wait for a selector, URL fragment, or fixed seconds."""
    action_name = "wait"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        target = step.wait_for or step.input_value
        if target:
            await _wait_for(page, target)
        else:
            await asyncio.sleep(2)
        return StepResult(step=step, status="passed")


class AssertCountAction(ActionStrategy):
    """
    Assert that the number of elements matching selectors == expected.
    Exam requirement: assert_reading_list_count.
    """
    action_name = "assert_count"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        selectors = step.extra.get("selectors", [])
        expected_from_context = step.extra.get("expected_from_context")
        delta = int(step.extra.get("delta", 0))
        if expected_from_context:
            if not context.has_count(expected_from_context):
                return StepResult(
                    step=step,
                    status="failed",
                    error=f"assert_count: missing count key '{expected_from_context}'",
                )
            expected = context.get_count(expected_from_context) + delta
        else:
            expected = int(step.extra.get("expected", 0)) + delta
        source = step.extra.get("source")

        if source == "context.paginated_data":
            actual = len(context.paginated_data)
        else:
            actual = 0
            for sel in selectors:
                items = await page.query_selector_all(sel)
                if items:
                    actual = len(items)
                    break

        if actual == expected:
            logger.info(f"✓ assert_count: {actual} == {expected}")
            return StepResult(step=step, status="passed")
        else:
            msg = f"assert_count FAILED: expected {expected}, got {actual}"
            logger.error(msg)
            return StepResult(step=step, status="failed", error=msg)


class StoreCountAction(ActionStrategy):
    """
    Store the count of elements matching selectors in context.
    Useful for "count before + delta" assertions.
    """
    action_name = "store_count"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        selectors = step.extra.get("selectors", [])
        context_key = step.extra.get("context_key", "count_before")

        if not selectors:
            return StepResult(
                step=step,
                status="failed",
                error="store_count: missing extra.selectors",
            )

        actual = 0
        for sel in selectors:
            try:
                items = await page.query_selector_all(sel)
                actual = max(actual, len(items))
            except Exception:
                continue

        context.set_count(context_key, actual)
        logger.info(f"✓ store_count: {context_key}={actual}")
        return StepResult(step=step, status="passed")


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
                       context: ExecutionContext) -> StepResult:
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
                       context: ExecutionContext) -> StepResult:
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


# ──────────────────────────────────────────────────────────
# PHASE 2 — Enhanced actions
# ──────────────────────────────────────────────────────────

class MeasurePerformanceAction(ActionStrategy):
    """
    Bonus: navigate to URL and measure web performance metrics.
    Writes performance_report.json.
    Exam bonus requirement.
    """
    action_name = "measure_performance"
    read_only   = True

    def __init__(self):
        self._default_output = _stepper_root / "artifacts" / "performance.json"
        self._default_output.parent.mkdir(parents=True, exist_ok=True)

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        url       = step.url or step.input_value
        threshold = step.extra.get("threshold_ms", 3000)

        await page.goto(url, wait_until="networkidle", timeout=30_000)

        metrics = await page.evaluate("""() => {
            const t = performance.timing;
            const p = performance.getEntriesByType('paint');
            return {
                load_time_ms:            t.loadEventEnd - t.navigationStart,
                dom_content_loaded_ms:   t.domContentLoadedEventEnd - t.navigationStart,
                first_paint_ms:          p.find(e => e.name === 'first-paint')?.startTime || null
            };
        }""")

        report = {**metrics, "url": url, "threshold_ms": threshold}

        if metrics["load_time_ms"] > threshold:
            logger.warning(f"Performance threshold exceeded: {metrics['load_time_ms']}ms > {threshold}ms")

        raw_path = Path(step.extra.get("output_path", "artifacts/performance.json"))
        output_path = raw_path if raw_path.is_absolute() else _stepper_root / raw_path
        if output_path != self._default_output:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"performance: {metrics} → {output_path}")
        return StepResult(step=step, status="passed")


class VisualCompareAction(ActionStrategy):
    """
    Take a screenshot and compare it against a stored baseline.

    First run (no baseline exists): saves the screenshot as the baseline and
    passes — so the first run always bootstraps the baseline automatically.

    Subsequent runs: pixel-diffs the current screenshot against the baseline.
    If the diff ratio exceeds `threshold` (default 0.01 = 1%), the step fails
    and a diff image is written next to the baseline for review.

    Step config (extra keys):
        snapshot_name  str   Required. Unique name for this comparison point.
                             e.g. "search-results-dune" or "shelf-after-add"
        threshold      float Optional. Max allowed diff ratio (0.0–1.0). Default 0.01.
        full_page      bool  Optional. Full-page screenshot. Default False.
        update         bool  Optional. If true, overwrite baseline with current shot.
                             Use this when an intentional UI change is approved.

    Baselines are stored in:  stepper/artifacts/baselines/<snapshot_name>.png
    Diff images are stored in: stepper/artifacts/baselines/<snapshot_name>.diff.png

    JSON example:
        {
            "action": "visual_compare",
            "description": "Shelf state after adding Dune books",
            "extra": {
                "snapshot_name": "shelf-after-dune-add",
                "threshold": 0.02
            }
        }

    To update a baseline after an approved UI change:
        {
            "action": "visual_compare",
            "extra": { "snapshot_name": "shelf-after-dune-add", "update": true }
        }
    """
    action_name = "visual_compare"
    read_only   = True

    def __init__(self):
        self._baselines_dir = _stepper_root / "artifacts" / "baselines"
        self._baselines_dir.mkdir(parents=True, exist_ok=True)

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        from PIL import Image, ImageChops, ImageEnhance
        import io

        snapshot_name = step.extra.get("snapshot_name")
        if not snapshot_name:
            return StepResult(
                step=step, status="failed",
                error="visual_compare requires extra.snapshot_name"
            )

        threshold  = float(step.extra.get("threshold", 0.01))
        full_page  = bool(step.extra.get("full_page", False))
        do_update  = bool(step.extra.get("update", False))

        baseline_path = self._baselines_dir / f"{snapshot_name}.png"
        diff_path     = self._baselines_dir / f"{snapshot_name}.diff.png"

        # Capture current state
        raw_bytes = await page.screenshot(full_page=full_page)
        current   = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

        # Update mode: overwrite baseline and pass
        if do_update:
            current.save(str(baseline_path))
            logger.info(f"visual_compare: baseline updated → {baseline_path}")
            return StepResult(step=step, status="passed",
                              output={"snapshot": snapshot_name, "mode": "updated"})

        # First run: no baseline yet — save and pass
        if not baseline_path.exists():
            current.save(str(baseline_path))
            logger.info(f"visual_compare: baseline created → {baseline_path}")
            return StepResult(step=step, status="passed",
                              output={"snapshot": snapshot_name, "mode": "baseline_created"})

        # Compare against baseline
        baseline = Image.open(str(baseline_path)).convert("RGB")

        # Resize current to match baseline dimensions if they differ
        # (can happen after viewport changes)
        if current.size != baseline.size:
            current = current.resize(baseline.size, Image.LANCZOS)

        diff_image = ImageChops.difference(baseline, current)
        pixels     = list(diff_image.getdata())
        total      = len(pixels)
        # Count pixels where any channel differs by more than 8/255 (noise floor)
        changed    = sum(1 for r, g, b in pixels if max(r, g, b) > 8)
        diff_ratio = changed / total

        if diff_ratio > threshold:
            # Amplify diff image so small differences are visible
            amplified = ImageEnhance.Brightness(diff_image).enhance(10)
            amplified.save(str(diff_path))
            msg = (
                f"Visual diff {diff_ratio:.2%} exceeds threshold {threshold:.2%} "
                f"for '{snapshot_name}'. Diff image → {diff_path}"
            )
            logger.warning(msg)
            return StepResult(
                step=step, status="failed", error=msg,
                screenshot=str(diff_path),
                output={"snapshot": snapshot_name, "diff_ratio": round(diff_ratio, 6),
                        "threshold": threshold, "diff_image": str(diff_path)},
            )

        logger.info(f"visual_compare: '{snapshot_name}' passed (diff={diff_ratio:.4%})")
        return StepResult(
            step=step, status="passed",
            output={"snapshot": snapshot_name, "diff_ratio": round(diff_ratio, 6),
                    "threshold": threshold},
        )


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

async def _wait_for(page, selector: str):
    try:
        if "/" in selector and not selector.startswith("//"):
            await page.wait_for_url(f"**{selector}**", timeout=10_000)
        else:
            await page.wait_for_selector(selector, timeout=10_000)
    except Exception:
        await asyncio.sleep(2)


def _resolve_input_value(value: str) -> tuple[str, bool]:
    if not isinstance(value, str):
        return value, False
    if value.startswith("ENV:"):
        key = value.split("ENV:", 1)[1]
        return os.environ.get(key, ""), True
    if value.startswith("${ENV:") and value.endswith("}"):
        key = value[6:-1]
        return os.environ.get(key, ""), True
    return value, False


async def _fetch_attr(locator, attr: str) -> str:
    """Fetch a single DOM attribute from a Playwright locator."""
    if attr == "innerText":
        return (await locator.inner_text()).strip()
    if attr == "innerHTML":
        return await locator.inner_html()
    if attr == "textContent":
        return (await locator.text_content() or "").strip()
    return await locator.get_attribute(attr) or ""


def _checked_input_value(step: StepConfig) -> tuple[str, StepResult | None]:
    """Resolve input_value, returning (value, None) on success or ("", StepResult) on missing env var."""
    value, was_env = _resolve_input_value(step.input_value)
    if was_env and not value:
        return "", StepResult(
            step=step,
            status="failed",
            error=f"Missing environment variable for value '{step.input_value}'",
        )
    return value, None


class ExtractDataAction(ActionStrategy):
    """
    Extract data from DOM elements on the current page.
    
    Returns a list of extracted values (text, URLs, attributes) that can be
    used by follow-up actions like PaginateAction or for_each_item.
    
    Step config expected:
        action: "extract_data"
        extra:
            selector: "CSS selector"  (required)
            attrs: ["href", "innerText"]  (optional — default: ["innerText"])
            limit: 100  (optional — max items to extract)
    
    Stores result in context["extracted_data"] = [list of values]
    """
    action_name = "extract_data"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        import time
        start = time.monotonic()
        
        try:
            selector = step.extra.get("selector")
            if not selector:
                return StepResult(
                    step=step,
                    status="failed",
                    error="Missing required field: extra.selector"
                )
            
            attrs = step.extra.get("attrs", ["innerText"])
            limit = step.extra.get("limit", 1000)
            wait_state = step.extra.get("wait_for_state", "visible")
            context_key = step.extra.get("context_key", "extracted_data")
            url_prefix = step.extra.get("url_prefix", "")
            dedupe = bool(step.extra.get("dedupe", False))
            allow_empty = step.extra.get("allow_empty", False)
            
            # Wait for selector to be present
            try:
                await page.wait_for_selector(selector, timeout=10_000, state=wait_state)
            except Exception as e:
                if allow_empty:
                    # Store empty result in typed context field
                    if context_key in ("collected_items", "collected_books"):
                        context.collected_items = []
                    else:
                        context.extracted_data = []
                    logger.info(f"✓ extract_data: 0 items (allow_empty) from '{selector}'")
                    return StepResult(step=step, status="passed")
                raise e
            
            # Query all matching elements
            locators = await page.locator(selector).all()
            extracted: list = []
            
            async def _fetch_element(loc):
                if len(attrs) == 1:
                    return await _fetch_attr(loc, attrs[0])
                values = await asyncio.gather(*[_fetch_attr(loc, attr) for attr in attrs])
                return dict(zip(attrs, values))

            extracted = list(await asyncio.gather(
                *[_fetch_element(loc) for loc in locators[:limit]]
            ))
            
            # Apply URL prefix if needed (converts relative hrefs to absolute URLs)
            if url_prefix:
                base = url_prefix.rstrip("/")
                extracted = [
                    base + v if isinstance(v, str) and v.startswith("/") else v
                    for v in extracted
                ]

            # Optional de-duplication (for scalar lists like hrefs)
            if dedupe and extracted and all(isinstance(v, str) for v in extracted):
                seen = set()
                deduped: list[str] = []
                for v in extracted:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)
                if len(deduped) != len(extracted):
                    logger.info(
                        f"extract_data: deduped {len(extracted)} -> {len(deduped)} items"
                    )
                extracted = deduped

            # Store in context — route to the typed field matching context_key
            if context_key in ("collected_items", "collected_books"):
                context.collected_items = extracted
            else:
                context.extracted_data = extracted

            logger.info(f"✓ extract_data: {len(extracted)} items from '{selector}'")
            return StepResult(
                step=step,
                status="passed",
                
            )
        
        except Exception as e:
            return StepResult(
                step=step,
                status="failed",
                error=f"extract_data: {str(e)}"
            )


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
                       context: ExecutionContext) -> StepResult:
        import time
        import re
        start = time.monotonic()
        
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
                    page, extract_step, resolver, context
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


class RunWorkflowAction(ActionStrategy):
    """
    Execute a sub-workflow JSON file at runtime, then return to the parent flow.

    Expected step.extra:
      path: str        # path to workflow JSON file (relative or absolute)
      vars: dict       # optional variable overrides for this subflow
      base_dir: str    # optional base dir for relative paths
    """
    action_name = "run_workflow"

    def __init__(self, run_steps_callable, base_dir: Path | None = None):
        self._run_steps = run_steps_callable
        self._base_dir = base_dir or Path.cwd()

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        from engine.planner.planner import _substitute

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

    def __init__(self, action_factory):
        self._factory = action_factory

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext) -> StepResult:
        import asyncio
        from playwright.async_api import async_playwright

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
                results = await self._run_isolated_browsers(sub_steps, resolver, context)
            else:
                results = await self._run_tabs(page, sub_steps, resolver, context)
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
                        resolver, context: ExecutionContext) -> list[StepResult]:
        """Spawn one new tab per sub-step in the same browser context."""
        browser_context = page.context

        async def run_one(sub_step: StepConfig) -> StepResult:
            tab = await browser_context.new_page()
            try:
                action = self._factory.create(sub_step.action)
                return await action.execute(tab, sub_step, resolver, context)
            except Exception as e:
                return StepResult(step=sub_step, status="failed", error=str(e))
            finally:
                await tab.close()

        return list(await asyncio.gather(*[run_one(s) for s in sub_steps]))

    async def _run_isolated_browsers(self, sub_steps: list[StepConfig],
                                     resolver, context: ExecutionContext) -> list[StepResult]:
        """Spawn one isolated browser per sub-step, each loaded with storage_state."""
        from pathlib import Path

        async def run_one(sub_step: StepConfig) -> StepResult:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                storage = _stepper_root / "artifacts" / "storage_state.json"
                ctx_kwargs = {}
                if storage.exists():
                    ctx_kwargs["storage_state"] = str(storage)
                ctx = await browser.new_context(**ctx_kwargs)
                tab = await ctx.new_page()
                try:
                    action = self._factory.create(sub_step.action)
                    return await action.execute(tab, sub_step, resolver, context)
                except Exception as e:
                    return StepResult(step=sub_step, status="failed", error=str(e))
                finally:
                    await browser.close()

        return list(await asyncio.gather(*[run_one(s) for s in sub_steps]))


# _dict_to_step_config is imported from engine.utils at the top of this file.
