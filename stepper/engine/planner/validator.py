"""
planner/validator.py — Validates AI-generated step plans against the action registry.

Collects ALL errors before raising so callers get a complete picture,
not just the first failure.
"""

from __future__ import annotations

import difflib

from stepper.engine.interfaces import StepConfig
from stepper.engine.planner.domains import domains_in_step, sub_step_dicts


class PlanValidationError(Exception):
    """Raised when one or more steps in a plan fail validation."""

    def __init__(self, message: str, bad_steps: list[StepConfig]):
        super().__init__(message)
        self.bad_steps = bad_steps


class PlanValidator:
    """
    Validates that every step in a plan references a registered action, carries
    a non-empty description, guards itself with conditions this run's domain
    actually understands, and names only domains the run can open.

    Usage:
        PlanValidator.validate(steps, registry, conditions, domains)
    """

    @staticmethod
    def validate(steps: list[StepConfig], registry,
                 conditions=None, domains=None) -> None:
        """
        Check all steps against the registry.
        Raises PlanValidationError listing every problem found.

        `conditions` is the run's ConditionRegistry. When given, every `when`
        clause is checked against it — a misspelled condition used to fail open
        at runtime and silently run the step it was meant to guard, so catching
        it here is the whole point of passing one.

        `domains` is the names of the domains registered for this run. When
        given, every step's action — and every sub-step's — must declare one of
        them. Without it the mismatch surfaces as UnknownDomainError partway
        through the run, after a browser has already launched (M5).
        """
        known = registry.names()
        errors: list[str] = []
        bad: list[StepConfig] = []
        saw_unknown_action = False
        saw_unknown_condition = False
        saw_unknown_domain = False

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

            # Sub-steps are steps, and get the same checks. They live in extra,
            # so the loop above never saw them: a typo inside a for_each_item
            # body passed validate and surfaced only at run time, after a
            # session had opened.
            for problem, unknown in _sub_step_errors(step.extra, known):
                saw_unknown_action = saw_unknown_action or unknown
                step_errors.append(problem)

            if not step.description:
                step_errors.append("missing 'description'")

            if conditions is not None:
                for bad_key in _unknown_conditions(step, conditions):
                    saw_unknown_condition = True
                    step_errors.append(
                        f"unknown when-condition '{bad_key}'"
                        + _did_you_mean(bad_key, conditions.names())
                    )

            if domains is not None:
                for action_name, domain in domains_in_step(step, registry):
                    if domain is None or domain in domains:
                        continue
                    saw_unknown_domain = True
                    step_errors.append(
                        f"action '{action_name}' acts on domain '{domain}', "
                        f"which this run has no session for"
                        + _did_you_mean(domain, sorted(domains))
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
            if saw_unknown_domain:
                message += ("\n\nRegistered domains:\n  "
                            + "\n  ".join(sorted(domains)))
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


def _sub_step_errors(extra, known: list[str]) -> list[tuple[str, bool]]:
    """
    The same checks a top-level step gets, applied to every sub-step below it.

    Returns (message, names_an_unknown_action) pairs, in order, duplicates
    kept: the same typo in two places is two things to fix, and the error list
    is what a person reads.

    A nested step is a step, so a missing action, an unregistered one and a
    missing description each have to fail validation the way they do at the top
    level. Extracting only the *names* that were already well-formed strings —
    the first version of this — silently dropped a sub-step with no action at
    all, which the factory then rejects at run time with a session already open.

    Only the dispatcher containers are walked (see SUB_STEP_KEYS). Treating
    every dict under `extra` as a possible step rejects legitimate data:
    `run_workflow` passes arbitrary `extra.vars` through, so
    `{"vars": {"action": "archive"}}` read as a sub-step naming an action.
    """
    found: list[tuple[str, bool]] = []
    for raw in sub_step_dicts(extra):
        action = raw.get("action")
        label  = raw.get("description") or action or "<empty sub-step>"

        if not isinstance(action, str) or not action:
            found.append((f"sub-step '{label}': missing 'action'", False))
        elif action not in known:
            found.append((
                f"unknown action '{action}' in a sub-step"
                + _did_you_mean(action, known), True))

        if not raw.get("description"):
            found.append((f"sub-step '{label}': missing 'description'", False))
    return found


def _did_you_mean(name: str, known: list[str], limit: int = 3) -> str:
    """Suggest the closest registered action names, or '' when nothing is close."""
    matches = difflib.get_close_matches(name, known, n=limit, cutoff=0.6)
    return f" — did you mean {', '.join(repr(m) for m in matches)}?" if matches else ""
