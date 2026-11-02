"""
brightsky/targets.py — A healed stepper element cfg as a BrightSky target.

`target_from_element` writes a step's new element the way bright-sky's
`readPlanStepTarget` reads a target, so a proposal can carry it. It keeps the
step's action: a role-less heal keeps the original target's role (which is
what makes `map_version` choose `fill`), but never its accessibleName or its
selectors, which are what missed. Nothing in this module does I/O.
"""

from __future__ import annotations

SCORE = 0.8
GROUNDING = "current_page"
#: `readPlanStepTarget`'s length caps (bright-sky, step-target.ts).
MAX_ROLE_LENGTH = 64
MAX_NAME_LENGTH = 512
MAX_SELECTOR_LENGTH = 1024


def target_from_element(element: dict, original: dict | None = None) -> dict | None:
    """A BrightSky `PlanStepTarget` for a stepper element cfg, or None when the store cannot express it.

    `original` is the step's stored target. When `element` gives no role+name,
    only `original`'s role is kept beside the healed selectors.
    """
    if not isinstance(element, dict):
        return None

    target: dict = {}
    role = _text(element, "role", MAX_ROLE_LENGTH)
    name = _text(element, "name", MAX_NAME_LENGTH)
    if role and name:
        target = {"role": role, "accessibleName": name}
    elif isinstance(original, dict):
        kept = _text(original, "role", MAX_ROLE_LENGTH)
        if kept:
            target = {"role": kept}

    # In the resolver cascade's priority order, so map_version (which takes the
    # first selector) looks the element up the way the heal found it.
    candidates: list[str] = []
    placeholder = _text(element, "placeholder")
    if placeholder:
        escaped = placeholder.replace("\\", "\\\\").replace('"', '\\"')
        candidates.append(f'[placeholder="{escaped}"]')
    element_id = _text(element, "id")
    if element_id:
        candidates.append("#" + element_id)
    for key in ("css", "xpath"):
        value = _text(element, key)
        if value:
            candidates.append(value)
    selectors = [s for s in candidates if len(s) <= MAX_SELECTOR_LENGTH]

    if "accessibleName" not in target and not selectors:
        return None
    target.update(selectors=selectors, score=SCORE, grounding=GROUNDING)
    return target


def _text(obj: dict, key: str, max_length: int | None = None) -> str | None:
    """`obj[key]` when it is a non-blank str within `max_length`, else None."""
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    if max_length is not None and len(value) > max_length:
        return None
    return value
