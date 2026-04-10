"""
utils.py — Shared utility functions for the Stepper framework.

Single source of truth for converting raw step dicts (from JSON or AI)
into StepConfig objects.  Previously duplicated in planner.py and
strategies.py — those copies are now removed.
"""

from __future__ import annotations

from stepper.interfaces import StepConfig


def dict_to_step_config(d: dict) -> StepConfig:
    """
    Convert a raw step dict (from workflow JSON or AI planner output)
    into a typed StepConfig.

    Extra fields: if the dict has an 'extra' key, its value is used directly.
    Otherwise every key that isn't a known top-level field is collected into
    extra (backward-compat for flat JSON steps).
    """
    extra_dict = d.get("extra", {}) if isinstance(d.get("extra"), dict) else {}
    if "extra" in d:
        extra_data = extra_dict
    else:
        _top_level = {
            "action", "description", "url", "element",
            "input_value", "wait_for", "value",
            "when", "retry", "retry_delay_ms",
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
    )
