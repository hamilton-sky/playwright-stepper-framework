"""
actions/basic.py — the page primitives.

One interaction each, on one element or one page: go somewhere, click, type,
hover, choose, wait, scroll, press a key, capture the screen. Nothing here
dispatches a sub-step or reads the execution context.

Pattern: Strategy + Template Method — the execute() skeleton lives on
ActionStrategy, every class below overrides _execute() only.

**A not-found element fails the step; it does not skip it.** These actions used
to report a skip when the resolver found nothing, which is the same status a
false `when:` clause produces for a step deliberately not run. A report
could not tell "we chose not to" from "we tried and could not", and because
`success_rate` is `passed / (passed + failed)` and the CLI exits on
`any(status == "failed")`, a click on an element that did not exist produced:

    {"passed": 1, "failed": 0, "skipped": 1, "success_rate": 1.0}   exit=0

Seven call sites across five actions had it. `skipped` now means one thing only:
a step that was deliberately not run. The healer is unaffected — StepRunner
fires it on `status in ("failed", "skipped")`, so the new status still heals.
"""

from __future__ import annotations
import asyncio
import logging
import re
from pathlib import Path

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
    CONFIDENCE_AUTO, CONFIDENCE_WARN,
)
from stepper.engine.actions._common import _wait_for, _checked_input_value, _strict

logger = logging.getLogger(__name__)


#: A URL that already names its scheme — http, https, file, about, data.
#: The test used to be `url.startswith("http")`, which reads as "is this
#: absolute?" and is not: it prepended https:// to `file:///tmp/x.html`,
#: producing `https://file///tmp/x.html`, and it left `httpbin.org` alone
#: because the *hostname* happens to begin with "http". Matching a scheme
#: asks the question that was meant. Bare hostnames and bare paths still get
#: https:// exactly as before.
_HAS_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


class NavigateAction(ActionStrategy):
    """
    Navigate to a URL and wait for the page to load.
    Handles both absolute URLs and relative paths.
    """
    action_name = "navigate"
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        url = step.input_value or step.url
        if not _HAS_SCHEME.match(url):
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
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        _, err = _checked_input_value(step)
        if err:
            return err
        # js_click reaches anything (a hidden dropdown button); force skips
        # Playwright's enabled checks but still needs a box to click. Each
        # tells the fallbacks which checks the click itself will skip.
        extra = step.extra or {}
        fit = ("click_js" if extra.get("js_click")
               else "click_force" if extra.get("force") else "click")
        result = await resolver.resolve(page, step.element, step.description,
                                        action=fit, strict=_strict(step))

        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"Element not found → {result.method}")

        if result.confidence < CONFIDENCE_WARN:
            # Below the gate the click does not happen, so this is a step that
            # did not act — the same thing a not-found element is. It used to
            # report `warned`, which no counter reads: `success_rate` is
            # passed/(passed+failed), the CLI exits on `any(failed)`, and the
            # heal loop fires on failed-or-skipped. A step the healer exists to
            # rescue was dropped silently instead.
            return StepResult(
                step=step, status="failed", confidence=result.confidence,
                error=f"Low confidence {result.confidence:.0%} (below "
                      f"{CONFIDENCE_WARN:.0%}) → not clicked",
            )

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
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        value, err = _checked_input_value(step)
        if err:
            return err

        result = await resolver.resolve(page, step.element, step.description,
                                        action="fill", strict=_strict(step))

        if not result.found:
            return StepResult(step=step, status="failed",
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
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        result = await resolver.resolve(page, step.element, step.description,
                                        action="hover", strict=_strict(step))

        if not result.found:
            return StepResult(step=step, status="failed",
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
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        result = await resolver.resolve(page, step.element, step.description,
                                        action="select", strict=_strict(step))

        if not result.found:
            return StepResult(step=step, status="failed",
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


class WaitAction(ActionStrategy):
    """Wait for a selector, URL fragment, or fixed seconds."""
    action_name = "wait"
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        target = step.wait_for or step.input_value
        if target:
            await _wait_for(page, target)
        else:
            await asyncio.sleep(2)
        return StepResult(step=step, status="passed")


class ScrollToAction(ActionStrategy):
    """Scroll a located element into the viewport. Used by healer step injection."""
    action_name = "scroll_to"
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        if not step.element:
            return StepResult(step=step, status="failed",
                              error="scroll_to: no element specified")
        result = await resolver.resolve(page, step.element, step.description)
        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"scroll_to: element not found → {step.element}")
        await result.locator.first.scroll_into_view_if_needed()
        logger.info(f"✓ scroll_to via {result.method}")
        return StepResult(step=step, status="passed")


class KeyboardPressAction(ActionStrategy):
    """Press a keyboard key, optionally focused on a resolved element."""
    action_name = "keyboard_press"
    domain      = "web"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        key = step.extra.get("key") or step.input_value
        if not key:
            return StepResult(step=step, status="failed",
                              error="keyboard_press: missing key (extra.key or input_value)")

        if step.element:
            result = await resolver.resolve(page, step.element, step.description)
            if not result.found:
                return StepResult(step=step, status="failed",
                                  error=f"keyboard_press: element not found → {step.element}")
            await result.locator.first.press(key)
            logger.info(f"✓ keyboard_press: '{key}' on {result.method}")
        else:
            await page.keyboard.press(key)
            logger.info(f"✓ keyboard_press: '{key}' (global)")

        return StepResult(step=step, status="passed")


class ScreenshotAction(ActionStrategy):
    """Take a screenshot and save it to screenshots/."""
    action_name = "screenshot"
    domain      = "web"
    read_only   = True

    def __init__(self, screenshots_dir: Path = Path("artifacts/screenshots")):
        self._screenshots_dir = screenshots_dir

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        label = (step.description or step.action).lower().replace(" ", "_")[:40]
        name = step.extra.get("filename") or f"screenshot_{label}.png"
        path = str(self._screenshots_dir / name)
        await page.screenshot(path=path, full_page=False)
        logger.info(f"📸 screenshot: {path}")
        return StepResult(step=step, status="passed", screenshot=path)
