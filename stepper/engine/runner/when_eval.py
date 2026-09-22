"""
when_eval.py — Evaluates `when` conditions for StepRunner.

Each step can carry an optional `when` dict. If present, StepRunner calls
evaluate_when() before executing the action. If it returns False, the step
is skipped with status="skipped".

Conditions are a registry, not an if/elif ladder. Core owns the combinators
and the context predicates; anything that has to look at a *session* belongs
to a domain — `url_contains` and `element_exists` are the web domain's, in
engine/browser/conditions.py, and an AWS domain could add `resource_exists`
without touching this file. See docs/universal-runner-plan.md §5.3, ticket T4.

Core conditions
---------------
{ "context_equals":        { "key": "count_before", "value": 0 } }
{ "context_key_exists":    "collected_items" }
{ "context_greater_than":  { "key": "gap", "value": 0 } }
{ "context_less_than":     { "key": "count", "value": 10 } }
{ "context_between":       { "key": "count", "min": 2, "max": 8 } }

Combinators (always available)
------------------------------
{ "not": <any condition> }
{ "all": [ <condition>, ... ] }
{ "any": [ <condition>, ... ] }

Examples in workflow JSON
--------------------------
Skip loop if nothing was collected:
  "when": { "context_key_exists": "collected_items" }

Combine (url_contains and element_exists come from the web domain):
  "when": { "all": [
    { "url_contains": "/account/login" },
    { "element_exists": "input[name='username']" }
  ]}

Unknown conditions
------------------
An unrecognised key used to fail OPEN: the evaluator logged a warning and ran
the step. A typo therefore ran a step that was meant to be guarded, which is
the one outcome a guard must never have. It is now an error, raised here and
caught by PlanValidator before a session is opened — so `validate` names the
bad key instead of a run silently doing the wrong thing.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from stepper.engine.interfaces import ExecutionContext

logger = logging.getLogger(__name__)

#: Structural keys handled by the registry itself rather than by an evaluator.
COMBINATORS = ("not", "all", "any")

#: An evaluator: (session, spec, context) -> bool. `session` is whatever the
#: domain opened — a Page for the web domain — and most evaluators ignore it.
ConditionEvaluator = Callable[[object, object, ExecutionContext], Awaitable[bool]]


class UnknownConditionError(ValueError):
    """Raised when a `when` clause names a condition no domain registered."""


class ConditionRegistry:
    """
    name -> (evaluator, domain), plus the combinators.

    Insertion order is the evaluation order: a condition dict carrying more
    than one recognised key is decided by whichever was registered first, which
    is what the if/elif ladder did by its own line order.

    Each condition records which domain's session it needs, so one `when` may
    name conditions from two domains at once:

        { "all": [ { "url_contains": "/receipt" },
                   { "db_row_exists": { "table": "orders" } } ] }

    The registry looks each session up and hands the evaluator that one object,
    which is why an evaluator's signature stays (session, spec, context) rather
    than taking the whole set and reaching into it. See M3 of
    docs/mixed-domain-plan.md.
    """

    def __init__(self, evaluators: dict[str, ConditionEvaluator] | None = None):
        # name -> (evaluator, domain). A plain dict of evaluators registers
        # them all as domain-free, which is what the core predicates are.
        self._evaluators: dict[str, tuple[ConditionEvaluator, str | None]] = {
            name: (fn, None) for name, fn in (evaluators or {}).items()
        }

    def register(self, name: str, evaluator: ConditionEvaluator,
                 domain: str | None = None) -> "ConditionRegistry":
        """
        Add a condition. `domain` names the session it needs, or None when it
        reads only the ExecutionContext — which every core predicate does.
        """
        if name in COMBINATORS:
            raise ValueError(f"'{name}' is a combinator and cannot be overridden")
        self._evaluators[name] = (evaluator, domain)
        return self  # fluent, like ActionRegistry.register

    def extend(self, other: "ConditionRegistry") -> "ConditionRegistry":
        """
        Copy another registry's evaluators in, keeping their order.

        Two domains claiming the same condition name is refused rather than
        resolved last-wins, for the reason ActionRegistry.register refuses a
        duplicate action: names are one flat namespace, and the only symptom of
        a silent overwrite is a `when` clause quietly asking the wrong session.
        Re-adding the *same* evaluator under the same domain is fine — every
        domain's registry starts from core_conditions(), so merging several
        always re-adds the core predicates.
        """
        for name, (evaluator, domain) in other._evaluators.items():
            existing = self._evaluators.get(name)
            if existing is not None and existing != (evaluator, domain):
                raise ValueError(
                    f"Condition '{name}' is already registered to domain "
                    f"{existing[1]!r}; {domain!r} cannot claim it too. "
                    f"Condition names share one namespace across every domain."
                )
            self._evaluators[name] = (evaluator, domain)
        return self

    def domain_of(self, name: str) -> str | None:
        """Which domain's session a registered condition needs."""
        entry = self._evaluators.get(name)
        return entry[1] if entry else None

    def names(self) -> list[str]:
        """Every recognised key, combinators included."""
        return sorted([*self._evaluators, *COMBINATORS])

    def __contains__(self, name: object) -> bool:
        return name in self._evaluators or name in COMBINATORS

    def unknown_keys(self, condition) -> list[str]:
        """
        Every key in a condition tree that no evaluator and no combinator
        claims. Used by PlanValidator; returns [] for a well-formed condition.

        Reports *all* unrecognised keys, including one sitting alongside a
        recognised one. At runtime the recognised key would win and the typo
        would be ignored silently, which is exactly the failure worth catching.
        """
        if not isinstance(condition, dict):
            return []
        unknown: list[str] = []
        for key, value in condition.items():
            if key == "not":
                unknown.extend(self.unknown_keys(value))
            elif key in ("all", "any"):
                if isinstance(value, list):
                    for sub in value:
                        unknown.extend(self.unknown_keys(sub))
            elif key not in self._evaluators:
                unknown.append(key)
        return unknown

    async def evaluate(self, condition: dict, context: ExecutionContext,
                       sessions=None) -> bool:
        """
        True → run the step. False → skip it.

        `sessions` is the run's SessionSet. A bare session is accepted too and
        wrapped, so a caller holding one object — a test, or the loop before
        routing existed — still works and every condition sees that object.

        An empty or absent condition is vacuously true, as it always was.
        """
        if not condition:
            return True

        from stepper.engine.session import SessionSet
        if not isinstance(sessions, SessionSet):
            sessions = SessionSet.single(sessions)

        for name, (evaluator, domain) in self._evaluators.items():
            if name in condition:
                session = await sessions.get(domain)
                result = await evaluator(session, condition[name], context)
                logger.debug(f"when.{name} → {result}")
                return result

        if "not" in condition:
            result = not await self.evaluate(condition["not"], context, sessions)
            logger.debug(f"when.not → {result}")
            return result

        if "all" in condition:
            for sub in condition["all"]:
                if not await self.evaluate(sub, context, sessions):
                    logger.debug("when.all → False (short-circuit)")
                    return False
            logger.debug("when.all → True")
            return True

        if "any" in condition:
            for sub in condition["any"]:
                if await self.evaluate(sub, context, sessions):
                    logger.debug("when.any → True (short-circuit)")
                    return True
            logger.debug("when.any → False")
            return False

        raise UnknownConditionError(
            f"Unknown when-condition {list(condition.keys())}. "
            f"Registered: {self.names()}"
        )


# ── Core evaluators ───────────────────────────────────────────────────────────
# None of these touches `session`: that is what makes them core.

async def _context_equals(session, spec, context: ExecutionContext) -> bool:
    return context.get(spec.get("key", "")) == spec.get("value")


async def _context_key_exists(session, spec, context: ExecutionContext) -> bool:
    """Exists AND is non-empty — None, [], 0 and "" all skip the step."""
    return bool(context.get(spec))


async def _context_greater_than(session, spec, context: ExecutionContext) -> bool:
    actual = context.get(spec.get("key", ""), 0)
    return (actual if actual is not None else 0) > spec.get("value", 0)


async def _context_less_than(session, spec, context: ExecutionContext) -> bool:
    actual = context.get(spec.get("key", ""), 0)
    return (actual if actual is not None else 0) < spec.get("value", 0)


async def _context_between(session, spec, context: ExecutionContext) -> bool:
    actual = context.get(spec.get("key", ""), 0)
    actual = actual if actual is not None else 0
    return spec.get("min", 0) <= actual <= spec.get("max", 0)


def core_conditions() -> ConditionRegistry:
    """
    The conditions every domain has, in the order the old ladder tried them.

    A domain with no session to inspect — see stepper/sites/_noop/ — needs
    nothing beyond these.
    """
    return ConditionRegistry({
        "context_equals":       _context_equals,
        "context_key_exists":   _context_key_exists,
        "context_greater_than": _context_greater_than,
        "context_less_than":    _context_less_than,
        "context_between":      _context_between,
    })


async def evaluate_when(condition: dict, context: ExecutionContext, page=None,
                        conditions: ConditionRegistry | None = None) -> bool:
    """
    Evaluate a when-condition against current state.

    `conditions` defaults to the core registry, so a caller that wants
    `url_contains` or `element_exists` passes the web domain's registry —
    engine.browser.conditions.web_conditions().
    """
    registry = conditions if conditions is not None else core_conditions()
    return await registry.evaluate(condition, context, page)
