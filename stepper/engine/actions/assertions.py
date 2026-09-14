"""
actions/assertions.py — check a fact about the page, or record one.

The assert_* actions fail the step when the page disagrees. The store_* actions
never fail on the value itself; they write it into the ExecutionContext for a
later step's `when:` clause or `${context.var}` interpolation to read.

They live together because they are the same operation either side of a
decision: read something off the page, then either judge it or remember it.
"""

from __future__ import annotations
import logging

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
)
from stepper.engine.actions._common import _fetch_attr

logger = logging.getLogger(__name__)


class AssertCountAction(ActionStrategy):
    """
    Assert that the number of elements matching selectors == expected.
    Exam requirement: assert_reading_list_count.
    """
    action_name = "assert_count"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
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


class AssertTextAction(ActionStrategy):
    """Assert that an element's text matches (or contains) an expected value."""
    action_name = "assert_text"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        result = await resolver.resolve(page, step.element, step.description)
        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"assert_text: element not found → {step.element}")

        expected = step.extra.get("expected", "")
        contains = bool(step.extra.get("contains", False))
        actual   = (await result.locator.first.inner_text()).strip()

        if contains:
            passed = expected in actual
        else:
            passed = actual == expected

        if passed:
            mode = "contains" if contains else "=="
            logger.info(f"✓ assert_text: '{actual}' {mode} '{expected}'")
            return StepResult(step=step, status="passed")

        mode_str = "to contain" if contains else "to equal"
        msg = f"assert_text FAILED: expected {mode_str} '{expected}', got '{actual}'"
        logger.error(msg)
        return StepResult(step=step, status="failed", error=msg)


class AssertVisibleAction(ActionStrategy):
    """Assert that an element is visible (or hidden if extra.hidden=true)."""
    action_name = "assert_visible"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        hidden = bool(step.extra.get("hidden", False))
        result = await resolver.resolve(page, step.element, step.description)

        if not result.found:
            if hidden:
                logger.info(f"✓ assert_visible(hidden): element absent, treated as hidden")
                return StepResult(step=step, status="passed")
            return StepResult(step=step, status="failed",
                              error=f"assert_visible: element not found → {step.element}")

        is_visible = await result.locator.first.is_visible()
        expected_visible = not hidden

        if is_visible == expected_visible:
            state = "hidden" if hidden else "visible"
            logger.info(f"✓ assert_visible: element is {state}")
            return StepResult(step=step, status="passed")

        expected_state = "hidden" if hidden else "visible"
        actual_state   = "visible" if is_visible else "hidden"
        msg = f"assert_visible FAILED: expected {expected_state}, element is {actual_state}"
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
                       context: ExecutionContext, behaviour=None) -> StepResult:
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


class StoreAction(ActionStrategy):
    """Store an element's text (or attribute) in context under extra.key."""
    action_name = "store"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        key = step.extra.get("key")
        if not key:
            return StepResult(step=step, status="failed",
                              error="store: missing extra.key")

        result = await resolver.resolve(page, step.element, step.description)
        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"store: element not found → {step.element}")

        attr  = step.extra.get("attr", "innerText")
        value = await _fetch_attr(result.locator.first, attr)

        context.store(key, value)
        logger.info(f"✓ store: {key}={value!r}")
        return StepResult(step=step, status="passed", output={key: value})
