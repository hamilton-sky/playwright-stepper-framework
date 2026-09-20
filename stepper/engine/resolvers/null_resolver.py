"""
resolvers/null_resolver.py — The resolver a domain with no elements gets.

StepRunner calls set_context_description() on its resolver before every single
action, unconditionally (leak L8). Passing resolver=None therefore did not mean
"this domain has no elements" — it meant every step failed with

    'NoneType' object has no attribute 'set_context_description'

recorded as the step's error and retried step.retry times. An AttributeError
laundered into a step failure is the worst of both: it does not crash, so it is
easy to miss, and it does not explain itself, so it is hard to diagnose.

NullResolver is the Null Object for that seam. Descriptions go nowhere, which
is correct — there is nothing to describe them to. But resolve() raises, and
says why, because an action that actually needs to find an element in a domain
that has none is a wiring mistake and should read like one.

See docs/universal-runner-plan.md §5.4, ticket T2.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class NoResolverError(RuntimeError):
    """Raised when an action needs element resolution and the domain has none."""


class NullResolver:
    """
    Satisfies the two methods callers use — set_context_description() and
    resolve() — without a page, a cascade or a model behind them.

    Deliberately not a subclass of ElementResolver: inheriting would drag the
    whole cascade's imports in, and the point of this class is that a
    non-browser domain pays for none of it.
    """

    def set_context_description(self, description: str) -> None:
        """No-op. There is no cascade to hand the description to."""
        return None

    async def resolve(self, page, cfg: dict, step_description: str = "",
                      *, strict: bool = False):
        """
        Always raises. The message names what was being looked for, because by
        the time this fires the useful question is which step wired an
        element-resolving action into a domain that has no elements.
        """
        wanted = step_description or (cfg or {}) or "an element"
        raise NoResolverError(
            f"This run has no element resolver, so {wanted!r} cannot be resolved. "
            f"Actions that locate elements need a domain that provides one — "
            f"pass resolver= to StepRunner, or use an action that does not "
            f"resolve elements."
        )
