"""
utils.py — Shared utility functions for the Stepper framework.

Single source of truth for converting raw step dicts (from JSON or AI)
into StepConfig objects.  Previously duplicated in planner.py and
strategies.py — those copies are now removed.
"""

from __future__ import annotations

from engine.interfaces import StepConfig


def dict_to_step_config(d: dict) -> StepConfig:
    """
    Convert a raw step dict (from workflow JSON or AI planner output)
    into a typed StepConfig.

    Extra fields: if the dict has an 'extra' key, its value is used directly.
    Otherwise every key that isn't a known top-level field is collected into
    extra (backward-compat for flat JSON steps).
    """
    if not isinstance(d, dict):
        raise ValueError("Each step must be an object")
    for key in ("extra", "element"):
        if key in d and not isinstance(d[key], dict):
            raise ValueError(f"{key} must be an object")
    for key in ("continue_on_failure", "skip_screenshot", "heal"):
        if key in d and type(d[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    for key in ("retry", "retry_delay_ms"):
        if key in d and (type(d[key]) is not int or d[key] < 0):
            raise ValueError(f"{key} must be a non-negative integer")
    extra_dict = d.get("extra", {}) if isinstance(d.get("extra"), dict) else {}
    if "extra" in d:
        extra_data = extra_dict
    else:
        _top_level = {
            "action", "description", "url", "element",
            "input_value", "wait_for", "value",
            "when", "retry", "retry_delay_ms", "continue_on_failure", "skip_screenshot",
            "heal", "heal_assert",
        }
        extra_data = {k: v for k, v in d.items() if k not in _top_level}

    return StepConfig(
        action=d.get("action", ""),
        description=d.get("description", ""),
        url=d.get("url", ""),
        element=d.get("element") or {},
        input_value=d.get("input_value") or d.get("value", ""),
        wait_for=d.get("wait_for", ""),
        extra=extra_data,
        when=d.get("when") or None,
        retry=int(d.get("retry", 0)),
        retry_delay_ms=int(d.get("retry_delay_ms", 1000)),
        continue_on_failure=bool(d.get("continue_on_failure", False)),
        skip_screenshot=bool(d.get("skip_screenshot", False)),
        heal=bool(d.get("heal", True)),
        heal_assert=d.get("heal_assert") or None,
    )
