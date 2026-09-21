"""
planner/validator.py — Validates AI-generated step plans against the action registry.

Collects ALL errors before raising so callers get a complete picture,
not just the first failure.
"""

from __future__ import annotations

import difflib

from stepper.engine.interfaces import StepConfig


class PlanValidationError(Exception):
    """Raised when one or more steps in a plan fail validation."""

    def __init__(self, message: str, bad_steps: list[StepConfig]):
        super().__init__(message)
        self.bad_steps = bad_steps


class PlanValidator:
    """
    Validates that every step in a plan references a registered action, carries
    a non-empty description, and guards itself with conditions this run's
    domain actually understands.

    Usage:
        PlanValidator.validate(steps, registry, conditions)
    """

    @staticmethod
    def validate(steps: list[StepConfig], registry, conditions=None) -> None:
        """
        Check all steps against the registry.
        Raises PlanValidationError listing every problem found.

        `conditions` is the run's ConditionRegistry. When given, every `when`
        clause is checked against it — a misspelled condition used to fail open
        at runtime and silently run the step it was meant to guard, so catching
        it here is the whole point of passing one.
        """
        known = registry.names()
        errors: list[str] = []
        bad: list[StepConfig] = []
        saw_unknown_action = False
        saw_unknown_condition = False

        for i, step in enumerate(steps, 1):
            step_errors: list[str] = []

            if not step.action:
                step_errors.append("missing 'action'")
            elif step.action not in known:
                saw_unknown_action = True
                step_errors.append(
                    f"unknown action '{step.action}'"
                    + _did_you_mean(step.action, known)
                )

            if not step.description:
                step_errors.append("missing 'description'")

            if conditions is not None:
                for bad_key in _unknown_conditions(step, conditions):
                    saw_unknown_condition = True
                    step_errors.append(
                        f"unknown when-condition '{bad_key}'"
                        + _did_you_mean(bad_key, conditions.names())
                    )

            if step_errors:
                label = step.description or step.action or "<empty step>"
                errors.append(f"Step {i} ({label}): " + "; ".join(step_errors))
                bad.append(step)

        if errors:
            message = f"{len(errors)} validation error(s):\n" + "\n".join(errors)
            # The full action list is long; print it once at the end rather than
            # repeating it inside every unknown-action error.
            if saw_unknown_action:
                message += "\n\nRegistered actions:\n  " + "\n  ".join(known)
            if saw_unknown_condition:
                message += ("\n\nRegistered when-conditions:\n  "
                            + "\n  ".join(conditions.names()))
            raise PlanValidationError(message, bad_steps=bad)


def _unknown_conditions(step: StepConfig, conditions) -> list[str]:
    """
    Unrecognised `when` keys on a step and on any sub-steps it carries.

    for_each_item, parallel and paginate hold their sub-steps as raw dicts in
    extra, so those `when` clauses never reach this validator as StepConfigs.
    They are checked here rather than left to fail at runtime, where the old
    fail-open behaviour is still the last resort.
    """
    found: list[str] = []
    if step.when:
        found.extend(conditions.unknown_keys(step.when))
    found.extend(_unknown_conditions_in(step.extra, conditions))
    return found


def _unknown_conditions_in(node, conditions) -> list[str]:
    """Walk raw sub-step dicts looking for `when` clauses."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "when":
                found.extend(conditions.unknown_keys(value))
            else:
                found.extend(_unknown_conditions_in(value, conditions))
    elif isinstance(node, list):
        for item in node:
            found.extend(_unknown_conditions_in(item, conditions))
    return found


def _did_you_mean(name: str, known: list[str], limit: int = 3) -> str:
    """Suggest the closest registered action names, or '' when nothing is close."""
    matches = difflib.get_close_matches(name, known, n=limit, cutoff=0.6)
    return f" — did you mean {', '.join(repr(m) for m in matches)}?" if matches else ""
