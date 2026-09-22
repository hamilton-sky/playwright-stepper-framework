"""
engine/browser/conditions.py — The web domain's `when` conditions.

`url_contains` and `element_exists` were two branches of the if/elif ladder in
when_eval.py — leak L5. They are the only conditions that look at the session,
and the session they look at is a Playwright Page, so they belong to the web
domain rather than to the engine's core vocabulary.

Registered as the web domain's conditions in bootstrap/session.py. A domain
with no browser gets core_conditions() and never sees these.

See docs/universal-runner-plan.md §5.3, ticket T4.
"""

from __future__ import annotations

import logging

from stepper.engine.interfaces import ExecutionContext
from stepper.engine.runner.when_eval import ConditionRegistry, core_conditions
from poms.shared.diagnostics import log_swallowed

logger = logging.getLogger(__name__)


async def url_contains(session, fragment, context: ExecutionContext) -> bool:
    """True when the page's current URL contains `fragment`."""
    current = session.url
    result  = fragment in current
    logger.debug(f"when.url_contains({fragment!r} in {current!r}) → {result}")
    return result


async def element_exists(session, selector, context: ExecutionContext) -> bool:
    """
    True when at least one element matches `selector`.

    Fails CLOSED: a selector that raises skips the step. That makes a code
    defect here look exactly like a condition that was legitimately false,
    which is a known sharp edge — but skipping a step whose precondition could
    not be established is the safer of the two wrong answers, and it is the
    behaviour workflows have been written against.
    """
    try:
        count  = await session.locator(selector).count()
        result = count > 0
    except Exception as exc:
        log_swallowed(f"when.element_exists[{selector!r}]", exc, logger)
        result = False
    logger.debug(f"when.element_exists({selector!r}) → {result}")
    return result


def web_conditions() -> ConditionRegistry:
    """Core plus the two that need a page — in the ladder's original order."""
    return (
        core_conditions()
        .register("url_contains", url_contains, domain="web")
        .register("element_exists", element_exists, domain="web")
    )
