"""
validator.py — Validate a list of planned StepConfigs against the ActionRegistry.

Used by the AI planner (before handing steps to the runner) and by AiHealer
(before accepting replacement steps from the LLM).
"""

from __future__ import annotations

from typing import Any

from engine.interfaces import StepConfig


class PlanValidationError(Exception):
    """Raised when one or more steps fail plan validation."""

    def __init__(self, message: str, bad_steps: list):
        super().__init__(message)
        self.bad_steps = bad_steps


class PlanValidator:
    """Validate plan steps in a single pass — collects ALL errors before raising."""

    @staticmethod
    def validate(steps: list[StepConfig], registry: Any) -> None:
        known = set(registry._registry.keys())
        errors: list[str] = []
        bad_steps: list[StepConfig] = []

        for idx, step in enumerate(steps):
            step_errors: list[str] = []

            action = getattr(step, "action", "") or ""
            description = getattr(step, "description", "") or ""

            if not action.strip():
                step_errors.append("missing 'action'")
            elif action not in known:
                step_errors.append(f"unknown action '{action}'")

            if not description.strip():
                step_errors.append("missing 'description'")

            if step_errors:
                bad_steps.append(step)
                errors.append(f"step[{idx}]: " + "; ".join(step_errors))

        if errors:
            raise PlanValidationError(
                "Plan validation failed:\n" + "\n".join(errors),
                bad_steps,
            )
