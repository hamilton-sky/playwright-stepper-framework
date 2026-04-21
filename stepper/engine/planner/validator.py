"""
planner/validator.py — Validates AI-generated step plans against the action registry.

Collects ALL errors before raising so callers get a complete picture,
not just the first failure.
"""

from __future__ import annotations

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
        known = set(registry._registry.keys())
        errors: list[str] = []
        bad: list[StepConfig] = []

        for i, step in enumerate(steps, 1):
            step_errors: list[str] = []

            if not step.action:
                step_errors.append("missing 'action'")
            elif step.action not in known:
                step_errors.append(
                    f"unknown action '{step.action}' — known: {sorted(known)}"
                )

            if not step.description:
                step_errors.append("missing 'description'")

            if step_errors:
                errors.append(f"Step {i}: " + "; ".join(step_errors))
                bad.append(step)

        if errors:
            raise PlanValidationError(
                f"{len(errors)} validation error(s):\n" + "\n".join(errors),
                bad_steps=bad,
            )
