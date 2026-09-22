"""
sites/db/params.py — turning `{{name}}` into a bound SQL parameter.

Two things in this domain take parameters — the three actions and the
`db_row_exists` condition — and both need the same resolution, so it lives
here rather than in either.

The walk itself lives in `stepper/engine/runner/interpolation.py`, shared with
the runner's own context pass and with sub-step substitution. Since that pass
runs before a step is dispatched, a workflow-driven `db_execute` arrives with
its params already resolved and this is a no-op. It still matters for the path
the runner is not on: these actions are called directly by tests and by any
programmatic caller, where nothing has resolved anything yet.

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

from stepper.engine.interfaces import ExecutionContext
from stepper.engine.runner.interpolation import context_lookup, names_in, resolve


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

    params, missing = resolve(raw, context_lookup(context))
    if missing:
        known = names_in(context)
        return params, (
            f"unresolved parameter reference(s) {missing}. "
            f"The context holds: {known or '(nothing yet)'}. "
            f"A {{{{name}}}} in params reads a value an earlier step stored; "
            f"workflow `variables` are substituted by the planner instead."
        )
    return params, ""
