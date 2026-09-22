"""
sites/db/pages/db_page.py — The db domain's three actions.

Like sites/_noop/, these subclass `ActionStrategy` rather than `GlueAction`:
`GlueAction` exists to enforce resolver and behaviour injection into POMs, and
this domain has no POMs because it has no selectors. `page` here is the
sqlite3.Connection SqliteSession handed over, and `resolver` is the
NullResolver every domain gets when it asks for nothing better.

Three actions, split the way the engine's own are (see
.claude/rules/design-patterns.md): one that acts, one that records into the
context, one that checks.

    db_execute       runs a statement       — changes state, commits
    db_query         reads one value        — stores it under a context key
    db_assert_count  counts rows            — reports a fact, passes or fails

**SQL values are bound, never interpolated.** `extra.params` is passed to
sqlite3 as parameters; a workflow cannot build a query by pasting a context
value into the SQL string, and nothing here does it on the workflow's behalf.
That is a correctness rule before it is a safety one — a stored value of
`O'Brien` interpolated into a string breaks the query, while bound it is simply
a value — but it is both, and the framework should not hand anyone the sharp
version.

`{{name}}` inside a param reads a value an earlier step stored — see
sites/db/params.py, which also explains why an unresolved one fails the step
rather than passing through.
"""

from __future__ import annotations

import logging

from stepper.engine.interfaces import (
    ActionStrategy, ExecutionContext, StepConfig, StepResult,
)
from stepper.engine.pages.base_page_module import PageModule
from stepper.sites.db.params import resolve_params

logger = logging.getLogger(__name__)


def _sql(step: StepConfig) -> str:
    return str(step.extra.get("sql", "")).strip()


class DbPage(PageModule):
    """The whole of the db domain's action surface."""

    site   = "db"
    domain = "db"

    class DbExecuteAction(ActionStrategy):
        """Run a statement that changes the database, and commit it."""

        action_name = "db_execute"
        read_only   = False

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            sql = _sql(step)
            if not sql:
                return StepResult(step=step, status="failed",
                                  error="db_execute: extra.sql is required")
            params, bad = resolve_params(step.extra.get("params", []), context)
            if bad:
                return StepResult(step=step, status="failed",
                                  error=f"db_execute: {bad}")
            try:
                cursor = page.execute(sql, params)
                page.commit()
            except Exception as exc:
                return StepResult(step=step, status="failed",
                                  error=f"db_execute: {type(exc).__name__}: {exc}")

            logger.info(f"db_execute: {cursor.rowcount} row(s) affected")
            return StepResult(step=step, status="passed",
                              output={"rowcount": cursor.rowcount})

    class DbQueryAction(ActionStrategy):
        """Read the first column of the first row into the execution context."""

        action_name = "db_query"
        read_only   = True           # safe inside ParallelAction

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            sql = _sql(step)
            key = step.extra.get("store_as", "")
            if not sql or not key:
                return StepResult(
                    step=step, status="failed",
                    error="db_query: extra.sql and extra.store_as are required")
            params, bad = resolve_params(step.extra.get("params", []), context)
            if bad:
                return StepResult(step=step, status="failed",
                                  error=f"db_query: {bad}")
            try:
                row = page.execute(sql, params).fetchone()
            except Exception as exc:
                return StepResult(step=step, status="failed",
                                  error=f"db_query: {type(exc).__name__}: {exc}")

            if row is None:
                return StepResult(step=step, status="failed",
                                  error=f"db_query: no rows for {sql!r}")

            value = row[0]
            # set_count keeps integers where the numeric `when` predicates can
            # read them; anything else is stored as-is.
            if isinstance(value, int) and not isinstance(value, bool):
                context.set_count(key, value)
            else:
                context.store(key, value)
            logger.info(f"db_query: {key}={value!r}")
            return StepResult(step=step, status="passed", output={key: value})

    class DbAssertCountAction(ActionStrategy):
        """Count rows and compare against extra.expected."""

        action_name = "db_assert_count"
        read_only   = True

        async def _execute(self, page, step: StepConfig, resolver,
                           context: ExecutionContext,
                           behaviour=None) -> StepResult:
            sql = _sql(step)
            if not sql or "expected" not in step.extra:
                return StepResult(
                    step=step, status="failed",
                    error="db_assert_count: extra.sql and extra.expected are required")
            params, bad = resolve_params(step.extra.get("params", []), context)
            if bad:
                return StepResult(step=step, status="failed",
                                  error=f"db_assert_count: {bad}")
            try:
                row = page.execute(sql, params).fetchone()
            except Exception as exc:
                return StepResult(step=step, status="failed",
                                  error=f"db_assert_count: {type(exc).__name__}: {exc}")

            actual   = 0 if row is None else int(row[0])
            expected = int(step.extra["expected"])
            if actual != expected:
                msg = f"db_assert_count FAILED: expected {expected}, got {actual}"
                logger.error(msg)
                return StepResult(step=step, status="failed", error=msg,
                                  output={"expected": expected, "actual": actual})

            logger.info(f"✓ db_assert_count: {actual} == {expected}")
            return StepResult(step=step, status="passed",
                              output={"expected": expected, "actual": actual})

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.DbExecuteAction(),
                             cls.DbQueryAction(), cls.DbAssertCountAction())
