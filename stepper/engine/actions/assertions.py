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
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        selectors = step.extra.get("selectors", [])
        expected_from_context = step.extra.get("expected_from_context")
        delta = int(step.extra.get("delta", 0))

        # Both halves of the comparison have to come from somewhere. Defaulting
        # either one made `{"action": "assert_count"}` with nothing else assert
        # 0 == 0 and report passed against any page at all.
        if expected_from_context:
            if not context.has_count(expected_from_context):
                return StepResult(
                    step=step,
                    status="failed",
                    error=f"assert_count: missing count key '{expected_from_context}'",
                )
            expected = context.get_count(expected_from_context) + delta
        elif "expected" in step.extra:
            expected = int(step.extra["expected"]) + delta
        else:
            return StepResult(
                step=step,
                status="failed",
                error="assert_count: extra.expected or extra.expected_from_context is "
                      "required — with neither, the step compares 0 against 0 and "
                      "passes whatever the page holds",
            )
        source = step.extra.get("source")

        if source == "context.paginated_data":
            actual = len(context.paginated_data)
        elif source:
            return StepResult(
                step=step,
                status="failed",
                error=f"assert_count: unknown extra.source '{source}' — the only "
                      "source is 'context.paginated_data'; drop it to count selectors",
            )
        elif not selectors:
            return StepResult(
                step=step,
                status="failed",
                error="assert_count: extra.selectors is required when no extra.source "
                      "is given — with neither there is nothing to count and the "
                      "actual is 0 regardless of the page",
            )
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
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        # An absent expected value is a broken step, not a satisfied one. It
        # defaulted to "", which `contains` finds inside every string on earth.
        if "expected" not in step.extra:
            return StepResult(step=step, status="failed",
                              error="assert_text: extra.expected is required — it "
                                    "defaulted to '', which every text contains")

        # strict: an assertion must check the element it names. Under the full
        # cascade a cfg that matches nothing falls through to a description-based
        # match, so the check passes against some other element entirely.
        result = await resolver.resolve(page, step.element, step.description, strict=True)
        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"assert_text: element not found → {step.element}")

        contains = bool(step.extra.get("contains", False))
        actual   = (await result.locator.first.inner_text()).strip()
        expected = step.extra["expected"]

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
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        hidden = bool(step.extra.get("hidden", False))
        # strict: an assertion must check the element it names. Under the full
        # cascade a cfg that matches nothing falls through to a description-based
        # match, so the check passes against some other element entirely.
        result = await resolver.resolve(page, step.element, step.description, strict=True)

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
    domain      = "web"
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
    domain      = "web"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        key = step.extra.get("key")
        if not key:
            return StepResult(step=step, status="failed",
                              error="store: missing extra.key")

        # strict, for the same reason as the assertions and with a longer tail:
        # a value read off the wrong element is stored under the right name, and
        # every `when:` clause and assertion downstream then reasons about it.
        result = await resolver.resolve(page, step.element, step.description, strict=True)
        if not result.found:
            return StepResult(step=step, status="failed",
                              error=f"store: element not found → {step.element}")

        attr  = step.extra.get("attr", "innerText")
        value = await _fetch_attr(result.locator.first, attr)

        context.store(key, value)
        logger.info(f"✓ store: {key}={value!r}")
        return StepResult(step=step, status="passed", output={key: value})
