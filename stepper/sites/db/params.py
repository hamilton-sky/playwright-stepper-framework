"""
sites/db/params.py — turning `{{name}}` into a bound SQL parameter.

Two things in this domain take parameters — the three actions and the
`db_row_exists` condition — and both need the same resolution, so it lives
here rather than in either.

Why this exists at all: the planner substitutes `{{name}}` from a workflow's
`variables` block *before the run starts*, which cannot see a value an earlier
step stored. A browser step scraping a price and a db step writing it is the
whole point of a mixed workflow, so params are resolved a second time, here,
against the ExecutionContext.

Two rules carry the weight.

**Resolution produces a bound parameter, never SQL.** The resolved value is
handed to sqlite3 as a parameter; nothing here builds a query string. That is a
correctness rule before it is a safety one — a stored value of `O'Brien`
interpolated into a string breaks the query, while bound it is just a value —
but it is both.

**An unresolved reference is an error.** Sub-step substitution leaves an
unknown token alone, deliberately, so a typo shows up in a log line rather than
as a silent blank. Here the opposite is right, and it was bought the hard way:
an unresolved `{{item}}` written to the database and then asserted with the
same unresolved `{{item}}` makes the check agree with itself, and the workflow
reports every step passed while the table holds the literal string `{{item}}`.
A stray token in a log is a nuisance; a stray token in the data, validated by a
comparison against itself, is a test that cannot fail.
"""

from __future__ import annotations

import re

from stepper.engine.interfaces import ExecutionContext

_REFERENCE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def resolve_params(raw, context: ExecutionContext) -> tuple[list | dict, str]:
    """
    Bound parameters for a statement, as sqlite3 wants them.

    A list binds `?` placeholders positionally; a dict binds `:name` ones. A
    bare scalar is wrapped rather than rejected, because `"params": 3` is what
    someone writes the first time and the intent is never ambiguous.

    Returns (params, error). A non-empty error names every reference the
    context could not answer, and the caller fails the step.
    """
    if not isinstance(raw, (list, dict)):
        raw = [raw]

    missing: list[str] = []
    if isinstance(raw, dict):
        resolved = {k: _resolve(v, context, missing) for k, v in raw.items()}
    else:
        resolved = [_resolve(v, context, missing) for v in raw]

    if missing:
        return resolved, (
            f"unresolved parameter reference(s) {missing}. "
            f"The context holds: {_known(context) or '(nothing yet)'}. "
            f"A {{{{name}}}} in params reads a value an earlier step stored; "
            f"workflow `variables` are substituted by the planner instead."
        )
    return resolved, ""


def _known(context: ExecutionContext) -> list[str]:
    """Every name the context can answer, for the error message."""
    named = [n for n in ExecutionContext._NAMED if getattr(context, n, None)]
    return sorted({*context.counts, *context._data, *named})


def _resolve(value, context: ExecutionContext, missing: list[str]):
    """
    Replace `{{name}}` with what the context holds under that name.

    A *pure* reference keeps the stored value's type, so an integer count binds
    as an integer; an embedded one is stringified. Same rule as sub-step
    substitution — see engine/actions/sub_step_mixin.py — because two spellings
    of one idea in a single workflow file would be worse than either alone.
    """
    if not isinstance(value, str):
        return value

    whole = _REFERENCE.fullmatch(value.strip())
    if whole:
        name = whole.group(1)
        if name not in context:
            missing.append(name)
            return value
        return context.get(name)

    def _one(match):
        name = match.group(1)
        if name not in context:
            missing.append(name)
            return match.group(0)
        return str(context.get(name))

    return _REFERENCE.sub(_one, value)
