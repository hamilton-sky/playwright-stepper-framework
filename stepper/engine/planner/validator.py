"""Validate plans and nested actions before launching a browser.

Action classes own parameter contracts; custom actions can opt in without
changing this validator. Pure runtime template references are deferred to execution.
"""
from __future__ import annotations

import difflib
import re

from engine.interfaces import StepConfig
from engine.utils import dict_to_step_config


class PlanValidationError(Exception):
    def __init__(self, message: str, bad_steps: list[StepConfig]):
        super().__init__(message)
        self.bad_steps = bad_steps


def _template(value):
    return isinstance(value, str) and re.fullmatch(r"\{\{[^{}]+\}\}", value) is not None


def _value(step, path):
    if path.startswith("extra."):
        return step.extra.get(path[6:]) if isinstance(step.extra, dict) else None
    return getattr(step, path, None)


def _matches(value, expected):
    types = expected if isinstance(expected, tuple) else (expected,)
    return type(value) in types or _template(value)


def _condition_errors(spec):
    if not isinstance(spec, dict) or len(spec) != 1:
        return ["when must contain exactly one condition (combine with all/any)"]
    key, value = next(iter(spec.items()))
    if key in {"all", "any"}:
        if not isinstance(value, list):
            return [f"when.{key} must be a list"]
        return [error for child in value for error in _condition_errors(child)]
    if key == "not":
        return _condition_errors(value)
    if key in {"url_contains", "element_exists", "context_key_exists"}:
        return [] if isinstance(value, str) and value else [f"when.{key} must be a non-empty string"]
    required = {
        "context_equals": {"key", "value"},
        "context_greater_than": {"key", "value"},
        "context_less_than": {"key", "value"},
        "context_between": {"key", "min", "max"},
    }.get(key)
    if required is None:
        return [f"unknown when condition '{key}'"]
    if not isinstance(value, dict) or not required <= value.keys():
        return [f"when.{key} requires {sorted(required)}"]
    if not isinstance(value["key"], str) or not value["key"]:
        return [f"when.{key}.key must be a non-empty string"]
    if key != "context_equals":
        for field in required - {"key"}:
            if not _matches(value[field], (int, float)):
                return [f"when.{key}.{field} must be numeric"]
    return []


def _assertion_errors(spec):
    allowed = {"url_contains", "url_not_contains", "element_visible", "element_text_contains"}
    if not isinstance(spec, dict) or not spec or set(spec) - allowed:
        return ["heal_assert must contain supported, non-empty assertions"]
    for key, value in spec.items():
        if key == "element_text_contains":
            if not isinstance(value, dict) or any(
                not isinstance(value.get(field), str) or not value[field]
                for field in ("selector", "text")
            ):
                return ["heal_assert.element_text_contains requires selector and text strings"]
        elif not isinstance(value, str) or not value:
            return [f"heal_assert.{key} must be a non-empty string"]
    return []


class PlanValidator:
    @staticmethod
    def validate(steps: list[StepConfig], registry) -> None:
        known = registry.names()
        errors = []
        bad = []

        def visit(step, location, depth=0):
            problems = []
            if depth > 30:
                problems.append("nested steps exceed depth limit (30)")
            if not isinstance(step.action, str) or step.action not in known:
                suggestions = difflib.get_close_matches(str(step.action), known, n=3, cutoff=0.6)
                problems.append(f"unknown action '{step.action}'" + (f" — did you mean {suggestions}?" if suggestions else ""))
            if not isinstance(step.description, str) or not step.description.strip():
                problems.append("missing 'description'")
            for field in ("url", "input_value", "wait_for"):
                if not isinstance(getattr(step, field), str):
                    problems.append(f"{field} must be a string")
            for field in ("element", "extra"):
                if not isinstance(getattr(step, field), dict):
                    problems.append(f"{field} must be an object")
            for field in ("retry", "retry_delay_ms"):
                value = getattr(step, field)
                if type(value) is not int or value < 0:
                    problems.append(f"{field} must be a non-negative integer")
            for field in ("heal", "continue_on_failure", "skip_screenshot"):
                if type(getattr(step, field)) is not bool:
                    problems.append(f"{field} must be a boolean")
            if step.when is not None:
                problems.extend(_condition_errors(step.when))
            if step.heal_assert is not None:
                problems.extend(_assertion_errors(step.heal_assert))
            if isinstance(step.action, str) and step.action in known and isinstance(step.extra, dict):
                action = registry.create(step.action)
                for path, expected in action.parameter_types.items():
                    value = _value(step, path)
                    if value is not None and not _matches(value, expected):
                        problems.append(f"{path} has invalid type")
                for alternatives in action.required_parameters:
                    if not any(_value(step, path) not in (None, "", [], {}) for path in alternatives):
                        problems.append(f"requires {' or '.join(alternatives)}")
                if depth <= 30:
                    for key in action.nested_steps:
                        children = step.extra.get(key, [])
                        if not isinstance(children, list):
                            problems.append(f"extra.{key} must be a list")
                            continue
                        for i, raw in enumerate(children, 1):
                            child_location = f"{location}.extra.{key}[{i}]"
                            try:
                                child = dict_to_step_config(raw)
                            except (ValueError, TypeError) as exc:
                                problems.append(f"{child_location}: {exc}")
                                continue
                            visit(child, child_location, depth + 1)
                            if step.action == "parallel" and isinstance(child.action, str) and child.action in known:
                                if not registry.create(child.action).read_only:
                                    problems.append(f"{child_location}: parallel requires read_only actions")
            if problems:
                errors.append(f"Step {location} ({step.action}): " + "; ".join(problems))
                bad.append(step)

        for i, step in enumerate(steps, 1):
            visit(step, str(i))
        if errors:
            raise PlanValidationError(f"{len(errors)} validation error(s):\n" + "\n".join(errors), bad)
