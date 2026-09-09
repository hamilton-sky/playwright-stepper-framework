"""
planner/validator.py — Validates AI-generated step plans against the action registry.

Collects ALL errors before raising so callers get a complete picture,
not just the first failure.
"""

from __future__ import annotations

import difflib

from engine.interfaces import StepConfig


class PlanValidationError(Exception):
    """Raised when one or more steps in a plan fail validation."""

    def __init__(self, message: str, bad_steps: list[StepConfig]):
        super().__init__(message)
        self.bad_steps = bad_steps


class PlanValidator:
    """
    Validates that every step in a plan references a registered action and
    carries a non-empty description.

    Usage:
        PlanValidator.validate(steps, registry)   # raises PlanValidationError on failure
    """

    @staticmethod
    def validate(steps: list[StepConfig], registry) -> None:
        """
        Check all steps against the registry.
        Raises PlanValidationError listing every problem found.
        """
        known = registry.names()
        errors: list[str] = []
        bad: list[StepConfig] = []
        saw_unknown_action = False

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
            raise PlanValidationError(message, bad_steps=bad)


def _did_you_mean(name: str, known: list[str], limit: int = 3) -> str:
    """Suggest the closest registered action names, or '' when nothing is close."""
    matches = difflib.get_close_matches(name, known, n=limit, cutoff=0.6)
    return f" — did you mean {', '.join(repr(m) for m in matches)}?" if matches else ""
