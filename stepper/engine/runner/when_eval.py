"""
when_eval.py — Evaluates `when` conditions for StepRunner.

Each step can carry an optional `when` dict. If present, StepRunner calls
evaluate_when() before executing the action. If it returns False, the step
is skipped with status="skipped".

Supported condition types
--------------------------
{ "context_equals":        { "key": "count_before", "value": 0 } }
{ "context_key_exists":    "collected_items" }
{ "context_greater_than":  { "key": "gap", "value": 0 } }
{ "context_less_than":     { "key": "count", "value": 10 } }
{ "context_between":       { "key": "count", "min": 2, "max": 8 } }
{ "url_contains":          "/account/login" }
{ "element_exists":        "input[name='username']" }
{ "not":                   <any condition> }
{ "all":                   [ <condition>, ... ] }
{ "any":                   [ <condition>, ... ] }

Examples in workflow JSON
--------------------------
Skip step if not on login page:
  "when": { "url_contains": "/account/login" }

Skip loop if nothing was collected:
  "when": { "context_key_exists": "collected_items" }

Skip fill if login form is already gone:
  "when": { "element_exists": "input[name='username']" }

Combine:
  "when": { "all": [
    { "url_contains": "/account/login" },
    { "element_exists": "input[name='username']" }
  ]}
"""

from __future__ import annotations
import logging

from engine.interfaces import ExecutionContext

logger = logging.getLogger(__name__)


async def evaluate_when(condition: dict, context: ExecutionContext, page) -> bool:
    """
    Evaluate a when-condition against current state.

    Returns True  → run the step
    Returns False → skip the step
    """
    if not condition:
        return True

    # ── context_equals ────────────────────────────────────────────────────────
    if "context_equals" in condition:
        spec = condition["context_equals"]
        key  = spec.get("key", "")
        val  = spec.get("value")
        result = context.get(key) == val
        logger.debug(f"when.context_equals({key!r}=={val!r}) → {result}")
        return result

    # ── context_key_exists ────────────────────────────────────────────────────
    if "context_key_exists" in condition:
        key = condition["context_key_exists"]
        val = context.get(key)
        # Exists AND is non-empty (None, [], "" are all falsy → skip)
        result = bool(val)
        logger.debug(f"when.context_key_exists({key!r}) → {result}")
        return result

    # ── context_greater_than ──────────────────────────────────────────────────
    if "context_greater_than" in condition:
        spec  = condition["context_greater_than"]
        key   = spec.get("key", "")
        value = spec.get("value", 0)
        actual = context.get(key, 0)
        result = (actual if actual is not None else 0) > value
        logger.debug(f"when.context_greater_than({key!r} > {value}) → {result}")
        return result

    # ── context_less_than ─────────────────────────────────────────────────────
    if "context_less_than" in condition:
        spec  = condition["context_less_than"]
        key   = spec.get("key", "")
        value = spec.get("value", 0)
        actual = context.get(key, 0)
        result = (actual if actual is not None else 0) < value
        logger.debug(f"when.context_less_than({key!r} < {value}) → {result}")
        return result

    # ── context_between ───────────────────────────────────────────────────────
    if "context_between" in condition:
        spec   = condition["context_between"]
        key    = spec.get("key", "")
        lo     = spec.get("min", 0)
        hi     = spec.get("max", 0)
        actual = context.get(key, 0)
        actual = actual if actual is not None else 0
        result = lo <= actual <= hi
        logger.debug(f"when.context_between({key!r} in [{lo}, {hi}]) → {result}")
        return result

    # ── url_contains ──────────────────────────────────────────────────────────
    if "url_contains" in condition:
        fragment = condition["url_contains"]
        current  = page.url
        result   = fragment in current
        logger.debug(f"when.url_contains({fragment!r} in {current!r}) → {result}")
        return result

    # ── element_exists ────────────────────────────────────────────────────────
    if "element_exists" in condition:
        selector = condition["element_exists"]
        try:
            count  = await page.locator(selector).count()
            result = count > 0
        except Exception:
            result = False
        logger.debug(f"when.element_exists({selector!r}) → {result}")
        return result

    # ── not ───────────────────────────────────────────────────────────────────
    if "not" in condition:
        inner  = condition["not"]
        result = not await evaluate_when(inner, context, page)
        logger.debug(f"when.not → {result}")
        return result

    # ── all (AND) ─────────────────────────────────────────────────────────────
    if "all" in condition:
        for sub in condition["all"]:
            if not await evaluate_when(sub, context, page):
                logger.debug("when.all → False (short-circuit)")
                return False
        logger.debug("when.all → True")
        return True

    # ── any (OR) ──────────────────────────────────────────────────────────────
    if "any" in condition:
        for sub in condition["any"]:
            if await evaluate_when(sub, context, page):
                logger.debug("when.any → True (short-circuit)")
                return True
        logger.debug("when.any → False")
        return False

    # Unknown condition type — log and allow (fail open, not fail closed)
    logger.warning(f"when: unknown condition keys {list(condition.keys())} — step will run")
    return True
