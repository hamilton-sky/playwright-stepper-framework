"""
The db domain — the second real domain, and what it found.

`_noop` proved the runner needs no browser. It could not prove the *domain
abstraction* is not browser-shaped, because it has nothing to open: no
configuration, no preflight, no session lifecycle, no failure modes. A sqlite3
connection has all four, so this is the first thing that actually tests the
contract M1–M5 built.

It found two bugs, and both have a test here.

**Conditions were resolved from the primary domain only.** M3 tagged every
condition with its domain and taught `evaluate` to look that domain's session
up in the SessionSet — but `main.py` composed the registry as
`get_domain(cfg.domain).conditions()`, so in a mixed run a db-tagged clause was
rejected at plan time as an unknown condition. The browser being the only
domain with conditions to tag is why it survived three tickets.

**An unresolved `{{reference}}` in a db param passed silently.** The planner
substitutes `{{name}}` from a workflow's `variables` before the run, which
cannot see a value `store` saved mid-run, so the literal went into the table —
and the assertion compared against the same literal and agreed with itself. A
workflow reported every step passed while the database held `{{item}}`.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from stepper.bootstrap.session import get_domain
from stepper.engine.interfaces import ExecutionContext, StepConfig
from stepper.engine.session import SessionAdapter
from stepper.sites.db.params import resolve_params
from stepper.sites.db.register import DB_DOMAIN
from stepper.sites.db.session import SqliteSession, db_preflight

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW  = _REPO_ROOT / "stepper" / "sites" / "db" / "workflows" / "db_smoke.json"


@pytest.fixture
def db_path(monkeypatch, tmp_path) -> Path:
    """A database this test owns. Never the configured default."""
    path = tmp_path / "stepper.db"
    monkeypatch.setenv("STEPPER_DB_PATH", str(path))
    return path


@pytest.fixture
async def connection(db_path):
    session = SqliteSession()
    conn = await session.open()
    yield conn
    await session.close()


def _step(action="db_execute", **extra) -> StepConfig:
    return StepConfig(action=action, description="a db step", extra=extra)


async def _run(action_name, context, conn, **extra):
    from stepper.sites.db.pages.db_page import DbPage

    actions = {
        "db_execute":      DbPage.DbExecuteAction(),
        "db_query":        DbPage.DbQueryAction(),
        "db_assert_count": DbPage.DbAssertCountAction(),
    }
    return await actions[action_name].execute(
        conn, _step(action_name, **extra), None, context, None)


# ── The domain itself ─────────────────────────────────────────────────────────

def test_the_domain_declares_everything_from_its_own_folder():
    """
    register_all_sites finds it by the same sites/*/register.py glob that finds
    saucedemo, and nothing outside stepper/sites/db/ names the db domain.
    """
    assert DB_DOMAIN.name == "db"
    assert DB_DOMAIN.session is SqliteSession
    assert DB_DOMAIN.preflight is db_preflight


def test_the_session_satisfies_the_adapter_protocol():
    assert isinstance(SqliteSession(), SessionAdapter)


async def test_the_session_hands_out_a_usable_connection(db_path):
    session = SqliteSession()
    conn = await session.open()

    conn.execute("CREATE TABLE t (a INT)")

    await session.close()
    assert db_path.exists()


async def test_close_commits_rather_than_discarding(db_path):
    """
    A workflow is a script someone wrote to make things happen. Rolling back at
    teardown would report every step passed and leave nothing behind — silence
    instead of a failure, which is the shape of bug this whole line of work
    exists to remove.
    """
    session = SqliteSession()
    conn = await session.open()
    conn.execute("CREATE TABLE t (a INT)")
    conn.execute("INSERT INTO t VALUES (1)")
    await session.close()

    after = sqlite3.connect(db_path)
    try:
        assert after.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        after.close()


async def test_closing_twice_is_harmless(db_path):
    """close_all runs in a finally; a second call must not raise."""
    session = SqliteSession()
    await session.open()
    await session.close()
    await session.close()


def test_the_session_never_imports_playwright():
    """The same claim test_noop_domain makes, for a domain that opens something."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from stepper.sites.db.register import DB_DOMAIN; "
         "print(any(m == 'playwright' or m.startswith('playwright.') for m in sys.modules))"],
        capture_output=True, text=True, cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", result.stdout


# ── Preflight ─────────────────────────────────────────────────────────────────

def test_a_writable_location_is_ready(db_path):
    assert db_preflight() == []


def test_a_parent_that_is_a_file_is_reported(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("STEPPER_DB_PATH", str(blocker / "stepper.db"))

    reasons = db_preflight()

    assert len(reasons) == 1 and "not a directory" in reasons[0]


def test_an_unwritable_directory_is_reported(monkeypatch, tmp_path):
    """
    Driven through os.access rather than chmod: the suite runs as root in some
    containers, and root passes almost every permission check, so a real chmod
    would make this pass for the wrong reason.
    """
    monkeypatch.setenv("STEPPER_DB_PATH", str(tmp_path / "stepper.db"))
    monkeypatch.setattr("stepper.sites.db.session.os.access", lambda p, m: False)

    reasons = db_preflight()

    assert len(reasons) == 1 and "not writable" in reasons[0]


def test_an_in_memory_database_needs_nothing(monkeypatch):
    monkeypatch.setenv("STEPPER_DB_PATH", ":memory:")

    assert db_preflight() == []


# ── Parameters are bound, and references resolve from the context ─────────────

def test_a_pure_reference_keeps_the_stored_type():
    context = ExecutionContext()
    context.set_count("n", 42)

    params, bad = resolve_params(["{{n}}"], context)

    assert params == [42] and not bad
    assert isinstance(params[0], int), "an int must not arrive as '42'"


def test_an_embedded_reference_is_stringified():
    context = ExecutionContext()
    context.store("name", "Dune")

    params, bad = resolve_params(["%{{name}}%"], context)

    assert params == ["%Dune%"] and not bad


def test_a_dict_of_named_parameters_resolves_too():
    context = ExecutionContext()
    context.store("name", "Dune")

    params, bad = resolve_params({"item": "{{name}}"}, context)

    assert params == {"item": "Dune"} and not bad


def test_a_bare_scalar_is_wrapped():
    assert resolve_params(3, ExecutionContext())[0] == [3]


def test_non_string_values_pass_through():
    params, bad = resolve_params([3, None, True], ExecutionContext())

    assert params == [3, None, True] and not bad


def test_an_unresolved_reference_is_an_error():
    """
    The bug: an unresolved {{item}} written to the table and then asserted with
    the same unresolved {{item}} makes the check agree with itself, and the
    workflow reports every step passed while the data is a literal token.
    """
    params, bad = resolve_params(["{{never_stored}}"], ExecutionContext())

    assert "never_stored" in bad
    assert "unresolved parameter reference" in bad


def test_the_error_says_what_the_context_does_hold():
    context = ExecutionContext()
    context.store("item", "Dune")

    _, bad = resolve_params(["{{itme}}"], context)

    assert "item" in bad, "a typo needs to see the name it nearly matched"


async def test_a_step_with_an_unresolved_reference_fails(connection):
    await _run("db_execute", ExecutionContext(), connection,
               sql="CREATE TABLE t (v TEXT)")

    result = await _run("db_execute", ExecutionContext(), connection,
                        sql="INSERT INTO t (v) VALUES (?)",
                        params=["{{never_stored}}"])

    assert result.status == "failed"
    assert "never_stored" in result.error


async def test_a_value_is_bound_not_interpolated(connection):
    """
    An apostrophe is the cheap proof: bound it is just a value, pasted into the
    SQL string it ends the literal and breaks the statement.
    """
    context = ExecutionContext()
    context.store("name", "O'Brien")
    await _run("db_execute", context, connection, sql="CREATE TABLE t (v TEXT)")

    written = await _run("db_execute", context, connection,
                         sql="INSERT INTO t (v) VALUES (?)", params=["{{name}}"])
    read = await _run("db_query", context, connection,
                      sql="SELECT v FROM t", store_as="back")

    assert written.status == "passed" and read.status == "passed"
    assert context.get("back") == "O'Brien"


# ── The actions ───────────────────────────────────────────────────────────────

async def test_db_query_stores_an_integer_where_the_numeric_predicates_find_it(connection):
    """
    `context_greater_than` reads counts. A count stored in the generic bucket
    would make a later `when` clause quietly compare against nothing.
    """
    context = ExecutionContext()
    await _run("db_execute", context, connection, sql="CREATE TABLE t (a INT)")
    await _run("db_execute", context, connection, sql="INSERT INTO t VALUES (1)")

    await _run("db_query", context, connection,
               sql="SELECT COUNT(*) FROM t", store_as="rows")

    assert context.get_count("rows") == 1


async def test_db_query_fails_when_there_are_no_rows(connection):
    context = ExecutionContext()
    await _run("db_execute", context, connection, sql="CREATE TABLE t (a INT)")

    result = await _run("db_query", context, connection,
                        sql="SELECT a FROM t", store_as="nothing")

    assert result.status == "failed" and "no rows" in result.error


async def test_db_assert_count_reports_both_numbers_on_failure(connection):
    context = ExecutionContext()
    await _run("db_execute", context, connection, sql="CREATE TABLE t (a INT)")

    result = await _run("db_assert_count", context, connection,
                        sql="SELECT COUNT(*) FROM t", expected=3)

    assert result.status == "failed"
    assert result.output == {"expected": 3, "actual": 0}


async def test_bad_sql_fails_the_step_rather_than_raising(connection):
    result = await _run("db_execute", ExecutionContext(), connection,
                        sql="NOT ACTUALLY SQL")

    assert result.status == "failed" and "OperationalError" in result.error


@pytest.mark.parametrize("action,missing", [
    ("db_execute", {}),
    ("db_query", {"sql": "SELECT 1"}),            # no store_as
    ("db_assert_count", {"sql": "SELECT 1"}),     # no expected
])
async def test_a_step_missing_its_required_extra_fails_clearly(connection, action, missing):
    result = await _run(action, ExecutionContext(), connection, **missing)

    assert result.status == "failed" and "required" in result.error


# ── The workflow, end to end, with no browser ─────────────────────────────────

def test_the_db_workflow_runs_without_a_browser(tmp_path):
    """
    The receipt, in a subprocess for the reason test_noop_domain gives: pytest
    shares one interpreter and another test legitimately imports playwright, so
    an in-process check would pass or fail on ordering.
    """
    import os

    env = {**os.environ, "STEPPER_DB_PATH": str(tmp_path / "smoke.db")}
    result = subprocess.run(
        [sys.executable, "stepper/main.py", "run", str(_WORKFLOW)],
        capture_output=True, text=True, cwd=_REPO_ROOT, env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "5/6 passed" in result.stdout + result.stderr
    assert (tmp_path / "smoke.db").exists()
