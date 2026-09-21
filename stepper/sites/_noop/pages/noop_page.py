"""
sites/_noop/pages/noop_page.py — Two actions that act on nothing.

This is the receipt for docs/universal-runner-plan.md: a domain with no
session to speak of, no hooks, no resolver and no POMs, discovered and
registered through exactly the same mechanism as the three browser sites.
Nothing here is meant to be useful at runtime — it is meant to make the
claim "the runner knows no domain" falsifiable, which
tests/unit/test_noop_domain.py then tries to falsify.

Note what is absent. These subclass ActionStrategy, not GlueAction: there is
no POM layer here because a POM exists to be the single home of CSS
selectors, and this domain has none. They never touch `page`, which for this
domain is the plain object NullSession hands out. They never touch `resolver`,
which is the NullResolver every domain gets when it asks for nothing better.
"""

from __future__ import annotations

import logging

from stepper.engine.interfaces import (
    ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class NoopPage(PageModule):
    """The whole of the noop domain's action surface."""

    site   = "noop"
    domain = "noop"

    class NoopSetAction(ActionStrategy):
        """Store a named integer in the execution context."""

        action_name = "noop_set"
        read_only   = False          # writes shared context

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            key   = step.extra.get("key", "")
            value = step.extra.get("value", 0)
            if not key:
                return StepResult(step=step, status="failed",
                                  error="noop_set: extra.key is required")
            context.set_count(key, int(value))
            logger.info(f"noop_set: {key}={value}")
            return StepResult(step=step, status="passed",
                              output={"key": key, "value": int(value)})

    class NoopEchoAction(ActionStrategy):
        """Read a named value back out of the context and report it."""

        action_name = "noop_echo"
        read_only   = True           # safe inside ParallelAction

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            key   = step.extra.get("key", "")
            value = context.get(key)
            if value is None:
                return StepResult(step=step, status="failed",
                                  error=f"noop_echo: nothing stored under {key!r}")
            logger.info(f"noop_echo: {key}={value}")
            return StepResult(step=step, status="passed",
                              output={key: value})

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.NoopSetAction(), cls.NoopEchoAction())
