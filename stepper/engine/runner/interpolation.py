"""
runner/interpolation.py — `{{name}}` resolved against the run's shared state.

There are two substitution passes in a run, and they answer different questions.

    Plan time    JsonFilePlanner, before the run starts.
                 Source: the workflow's own `variables` block.
                 Deterministic — the same JSON yields the same StepConfig list.

    Run time     this module, before each step is dispatched.
                 Source: the ExecutionContext, which earlier steps wrote to.

This one used to be `StepRunner._resolve_count_vars`, and it was narrower than
the docs beside it claimed, on two axes at once: it read `context.counts` only,
and it walked `step.extra` only. Both limits had the same effect — a value a
browser step captured with `store` could not be passed to a later step, because
`store` writes the context's generic bucket rather than `counts`. That is the
ordinary shape of a mixed-domain workflow (scrape a value, write it through
SQL), and it was the one thing the mechanism could not do.

Now the source is whatever `context.get` answers — counts, the generic store
and the named fields alike — and every data field of a step is walked.

## An unresolved reference fails the step

Plan-time and sub-step substitution both leave an unknown token alone, so a
typo shows up in a log line rather than as a silent blank. Here the opposite is
right, and M6 paid for the lesson: an unresolved `{{item}}` written into a
database and then asserted against the same unresolved `{{item}}` makes the
check agree with itself, and the workflow reports every step passed while the
table holds the literal string. A token that reaches an action's arguments is
not a cosmetic problem.

Silence was also the old behaviour's real cost. `{{gap}}` in a field this pass
did not walk did not warn — it arrived at a POM as a string and died three
frames down as `'<' not supported between instances of 'int' and 'str'`.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: `{{ name }}` — whitespace tolerated, the name captured.
REFERENCE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def has_reference(node: Any) -> bool:
    """
    Cheap scan, so a step with no tokens skips the copy entirely.

    Most steps in most workflows carry none; the walk below builds new dicts and
    lists as it goes, and doing that per step for nothing is waste on the hot
    path.
    """
    if isinstance(node, str):
        return "{{" in node
    if isinstance(node, dict):
        return any(has_reference(v) for v in node.values())
    if isinstance(node, list):
        return any(has_reference(v) for v in node)
    return False


def resolve(node: Any, lookup) -> tuple[Any, list[str]]:
    """
    Replace every `{{name}}` in `node` using `lookup`.

    `lookup` is a callable taking a name and returning `(found, value)` — a
    two-part answer rather than a sentinel, because `None` and `0` are values a
    step may legitimately have stored.

    Returns `(resolved, missing)`. `missing` lists every name the lookup could
    not answer, in the order encountered and without duplicates; the caller
    decides what that means.

    A *pure* reference keeps the stored value's type, so an integer count binds
    as an integer and a later comparison behaves. An *embedded* one is
    stringified, since there is nothing else it could become inside a sentence.
    Containers are embedded as JSON rather than `str(...)`, which would emit
    Python literals nothing downstream can parse.
    """
    missing: list[str] = []
    resolved = _walk(node, lookup, missing)
    return resolved, list(dict.fromkeys(missing))


def _walk(node: Any, lookup, missing: list[str]) -> Any:
    if isinstance(node, str):
        return _resolve_str(node, lookup, missing)
    if isinstance(node, dict):
        return {k: _walk(v, lookup, missing) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, lookup, missing) for v in node]
    return node


def _resolve_str(value: str, lookup, missing: list[str]) -> Any:
    whole = REFERENCE.fullmatch(value.strip())
    if whole:
        found, resolved = lookup(whole.group(1))
        if not found:
            missing.append(whole.group(1))
            return value
        return resolved

    def _one(match: re.Match) -> str:
        found, resolved = lookup(match.group(1))
        if not found:
            missing.append(match.group(1))
            return match.group(0)
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved)
        return str(resolved)

    return REFERENCE.sub(_one, value)


# ── Lookups ───────────────────────────────────────────────────────────────────

def context_lookup(context):
    """
    Read a name from an ExecutionContext: counts, the generic store, and the
    named fields — everything `context.get` answers.

    `__contains__` is what decides *found*, so a stored `None` or `0` resolves
    to itself rather than being reported missing.
    """
    def _look(name: str):
        if name in context:
            return True, context.get(name)
        return False, None
    return _look


def mapping_lookup(mapping: dict):
    """Read a name from a plain dict — what sub-step substitution passes."""
    def _look(name: str):
        if name in mapping:
            return True, mapping[name]
        return False, None
    return _look


def names_in(context) -> list[str]:
    """
    Every name a context can answer, for an error message.

    Named fields are listed only when non-empty: `context.get` returns the
    default for an empty one, so offering `collected_items` as a candidate when
    nothing has collected anything would be a misleading suggestion.
    """
    from stepper.engine.interfaces import ExecutionContext

    named = [n for n in ExecutionContext._NAMED if getattr(context, n, None)]
    return sorted({*context.counts, *context._data, *named})
