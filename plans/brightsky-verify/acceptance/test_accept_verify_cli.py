"""
brightsky-verify acceptance: `python3 -m stepper brightsky verify ...` and the
verify loop (`verify.verify_slug`, `verify.verify_all_unverified`).

Source: spec.md, stories "Verify one workflow", "Walk the queue" and "Versions
that are not current", the Happy path, the Edge cases table and Interfaces.
The CLI reaches the network and the browser only through
`verify.make_client` and `verify.make_executor`, which these tests replace.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bs_harness import (
    QUEUE_PATH,
    SLUG,
    TOKEN,
    FakeBackend,
    StubExecutor,
    detail_json,
    detail_path,
    engine_world,
    error_body,
    make_client,
    pilot_backend,
    pilot_steps,
    queue_item,
    run_cli,
    run_report,
    run_view,
    runs_path,
    steps_by_number,
    version_view,
    versions_path,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _no_token_anywhere(result, caplog):
    assert TOKEN not in result.out
    assert TOKEN not in result.err
    assert TOKEN not in caplog.text


# ── Verify one workflow ───────────────────────────────────────────────────────

# Story: With `BRIGHTSKY_API_URL` and `BRIGHTSKY_BRIDGE_TOKEN` set and every step
#        passing, the command posts one run report with `result: "passed"`. Every
#        step in it has `outcome: "passed"`, `matched: true` and a non-empty
#        `tier`, and the report carries one `idempotencyKey`. The command exits 0.
# Happy path 5-6: `POST .../runs` with `version`, three `passed` steps,
#        `result: "passed"`, `client: "stepper"` and one idempotency key ... The
#        CLI prints `openlibrary-find-author v1 passed` and exits 0.
def test_a_full_pass_reports_every_step_passed_with_one_idempotency_key(
        monkeypatch, capsys, caplog):
    backend = pilot_backend()
    world = engine_world(monkeypatch)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 0, result.err
    report = run_report(backend)
    assert report["version"] == 1
    assert report["result"] == "passed"
    assert report["client"] == "stepper"
    assert isinstance(report["idempotencyKey"], str)
    assert 1 <= len(report["idempotencyKey"]) <= 100
    assert sorted(s["stepNumber"] for s in report["steps"]) == [1, 2, 3]
    for step in report["steps"]:
        assert step["outcome"] == "passed"
        assert step["matched"] is True
        assert isinstance(step["tier"], str) and step["tier"].strip()
    assert backend.sent("POST", versions_path()) == []
    assert f"{SLUG} v1 passed" in result.lines
    _no_token_anywhere(result, caplog)


# Happy path 1-2: `GET /api/workflows/verification-queue` answers 200, so the
#        token is accepted ... `GET /api/workflows/openlibrary-find-author`
#        returns `currentVersion` and `currentSteps`.
def test_verify_checks_the_token_then_fetches_then_reports(monkeypatch, capsys):
    backend = pilot_backend()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 0, result.err
    assert backend.calls() == [
        ("GET", QUEUE_PATH), ("GET", detail_path()), ("POST", runs_path()),
    ]


# Story: When a step fails and is not healed, the report has `result: "failed"`
#        and that step has `outcome: "failed"`. Steps after the hard stop have
#        `outcome: "unchecked"`. No version is proposed. The command exits 1.
def test_a_failed_unhealed_step_is_reported_failed_and_later_steps_unchecked(
        monkeypatch, capsys):
    backend = pilot_backend()
    world = engine_world(monkeypatch, broken=(2,))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    report = run_report(backend)
    assert report["result"] == "failed"
    steps = steps_by_number(report)
    assert steps[1]["outcome"] == "passed"
    assert steps[2]["outcome"] == "failed"
    assert steps[3]["outcome"] == "unchecked"
    assert backend.sent("POST", versions_path()) == []
    assert any(line.startswith(f"{SLUG} v1 failed") for line in result.lines)


# Story: When either variable is missing or blank, the command prints
#        `error: BRIGHTSKY_API_URL is not set` (or `BRIGHTSKY_BRIDGE_TOKEN`) to
#        stderr, makes no HTTP request, and exits 3. No traceback is shown.
@pytest.mark.parametrize("missing", ["BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"])
@pytest.mark.parametrize("blank", [False, True], ids=["missing", "blank"])
def test_missing_env_exits_3_with_a_message_and_no_request(monkeypatch, capsys, missing,
                                                           blank):
    env = {"BRIGHTSKY_API_URL": "http://localhost:3001", "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    if blank:
        env[missing] = "  "
    else:
        del env[missing]
    backend = pilot_backend()
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor, env=env)

    assert result.code == 3
    assert f"error: {missing} is not set" in result.err
    assert "Traceback" not in result.err
    assert backend.requests == []
    assert executor.calls == []


def test_missing_env_exits_3_from_the_real_entry_point():
    """The same criterion through `python3 -m stepper`, in a fresh process."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN")}
    env["PYTHONPATH"] = str(_REPO_ROOT)

    proc = subprocess.run(
        [sys.executable, "-m", "stepper", "brightsky", "verify", SLUG],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )

    assert proc.returncode == 3, proc.stderr
    assert "error: BRIGHTSKY_API_URL is not set" in proc.stderr
    assert "Traceback" not in proc.stderr


# Edge: `BRIGHTSKY_API_URL` is `http://` to a non-loopback host, or not http(s) |
#       `error:` saying the token is only sent over https ..., exit 3
@pytest.mark.parametrize("url", ["http://bright-sky.example.com", "ftp://bright-sky.example.com"])
def test_a_url_that_would_leak_the_token_exits_3(monkeypatch, capsys, caplog, url):
    backend = pilot_backend()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG], backend=backend,
                     env={"BRIGHTSKY_API_URL": url, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN})

    assert result.code == 3
    assert "error:" in result.err and "https" in result.err
    assert backend.requests == []
    _no_token_anywhere(result, caplog)


# Story: When the slug is malformed (it does not match `^[a-z0-9-]{3,100}$`), or
#        the backend answers 404 to the fetch, the command prints `error: ...`
#        naming the problem and exits 3.
@pytest.mark.parametrize("slug", ["ab", "Find-Author", "find_author", "a" * 101, "x/../y"])
def test_a_malformed_slug_exits_3(monkeypatch, capsys, slug):
    backend = pilot_backend()
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", slug],
                     backend=backend, executor=executor)

    assert result.code == 3
    assert "error:" in result.err
    assert "slug" in result.err.lower()
    assert executor.calls == []
    assert not backend.sent("GET", f"/api/workflows/{slug}")


def test_a_404_on_the_fetch_exits_3(monkeypatch, capsys):
    backend = pilot_backend()
    backend.on("GET", detail_path(), (404, error_body(404, "Workflow not found")))
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor)

    assert result.code == 3
    assert "error:" in result.err
    assert "Workflow not found" in result.err or "404" in result.err
    assert executor.calls == []
    assert backend.sent("POST", runs_path()) == []


# Story: A wrong or revoked token is caught before any browser run ... `verify
#        <slug>` first makes one guarded call, `GET
#        /api/workflows/verification-queue` ... A 401 or 403 there prints `error:
#        bridge token rejected (HTTP <status>): <backend message>` to stderr, sends
#        no other request, launches no browser, and exits 3. The stubbed transport
#        sees exactly one request, and the token is not in the output.
@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_token_exits_3_before_any_browser_run(monkeypatch, capsys, caplog,
                                                          status):
    backend = pilot_backend()
    backend.on("GET", QUEUE_PATH, (status, error_body(status, "Invalid bridge token")))
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor)

    assert result.code == 3
    assert f"error: bridge token rejected (HTTP {status}): Invalid bridge token" in result.err
    assert backend.calls() == [("GET", QUEUE_PATH)]
    assert executor.calls == []
    _no_token_anywhere(result, caplog)


# Story: A 401 or 403 on `POST /runs` or `POST /versions` (a token revoked
#        mid-run) prints the same `bridge token rejected` error and exits 3.
@pytest.mark.parametrize("status", [401, 403])
def test_a_token_revoked_before_the_run_report_exits_3(monkeypatch, capsys, caplog, status):
    backend = pilot_backend()
    backend.on("POST", runs_path(), (status, error_body(status, "Token revoked")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 3
    assert f"error: bridge token rejected (HTTP {status}): Token revoked" in result.err
    assert len(backend.sent("POST", runs_path())) == 1
    _no_token_anywhere(result, caplog)


def test_a_token_revoked_before_the_proposal_exits_3(monkeypatch, capsys, caplog):
    from bs_harness import HEALED_LINK, is_step

    backend = pilot_backend()
    backend.on("POST", versions_path(), (401, error_body(401, "Token revoked")))
    world = engine_world(monkeypatch, broken=(2,),
                         direct=lambda s: {"css": HEALED_LINK} if is_step(2)(s) else None)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 401): Token revoked" in result.err
    assert len(backend.sent("POST", versions_path())) == 1
    _no_token_anywhere(result, caplog)


# Story: In `--all-unverified` it stops the walk there: no later entry is run.
def test_a_token_revoked_mid_walk_stops_the_walk(monkeypatch, capsys):
    backend = FakeBackend()
    backend.on("GET", QUEUE_PATH, (200, [queue_item("first-flow", 1),
                                         queue_item("second-flow", 1)]))
    for slug in ("first-flow", "second-flow"):
        backend.on("GET", detail_path(slug), (200, detail_json(slug)))
    backend.on("POST", runs_path("first-flow"), (403, error_body(403, "Token revoked")))
    backend.on("POST", runs_path("second-flow"), (201, run_view("second-flow")))
    executor = StubExecutor(["pass"])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 403): Token revoked" in result.err
    assert not any("second-flow" in r.path for r in backend.requests)
    assert len(executor.calls) == 1


# Story: Passing both a slug and `--all-unverified`, or neither, prints a usage
#        error and exits 3.
@pytest.mark.parametrize("args", [
    ["brightsky", "verify", SLUG, "--all-unverified"],
    ["brightsky", "verify"],
])
def test_both_or_neither_of_slug_and_all_unverified_is_a_usage_error(monkeypatch, capsys,
                                                                     args):
    backend = pilot_backend()
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, args, backend=backend, executor=executor)

    assert result.code == 3
    assert result.err.strip()
    assert "error" in result.err.lower() or "usage" in result.err.lower()
    assert backend.requests == []
    assert executor.calls == []


# Interfaces: `--version` is parsed and checked by the command itself (a
#             positive integer, else exit 3). An option argparse does not
#             recognise is still argparse's usage error, which exits 2.
@pytest.mark.parametrize("value", ["0", "-1", "two", "1.5"])
def test_a_version_that_is_not_a_positive_integer_exits_3(monkeypatch, capsys, value):
    backend = pilot_backend()

    result = run_cli(monkeypatch, capsys,
                     ["brightsky", "verify", SLUG, f"--version={value}"], backend=backend)

    assert result.code == 3
    assert "error:" in result.err
    assert backend.requests == []


def test_an_unknown_option_is_argparse_usage_error_exit_2(monkeypatch, capsys):
    result = run_cli(monkeypatch, capsys,
                     ["brightsky", "verify", "--all-unverified", "--bogus-flag"],
                     backend=pilot_backend())

    assert result.code == 2
    assert "--bogus-flag" in result.err


# Interfaces: `brightsky verify <slug> [--version N] [--show]` — runs headless
#             unless --show.
def test_verify_runs_headless_by_default_and_headed_with_show(monkeypatch, capsys):
    executor = StubExecutor(["pass"])
    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=pilot_backend(), executor=executor)
    assert result.code == 0, result.err
    assert [c["headless"] for c in executor.calls] == [True]

    shown = StubExecutor(["pass"])
    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG, "--show"],
                     backend=pilot_backend(), executor=shown)
    assert result.code == 0, result.err
    assert [c["headless"] for c in shown.calls] == [False]


# Edge: 5xx or network error / timeout on the token check, the queue read or the
#       fetch | one retry after a backoff; a second failure prints `error: ...`
#       to stderr and exits 1
@pytest.mark.parametrize("where", ["token check", "fetch"])
@pytest.mark.parametrize("failure", ["5xx", "network"])
def test_a_second_failure_before_the_run_exits_1(monkeypatch, capsys, where, failure):
    path = QUEUE_PATH if where == "token check" else detail_path()
    response = (503, error_body(503, "busy")) if failure == "5xx" else OSError("refused")
    backend = pilot_backend()
    backend.on("GET", path, response)
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert "error:" in result.err
    assert len(backend.sent("GET", path)) == 2
    assert executor.calls == []


def test_a_second_failure_on_the_queue_read_exits_1(monkeypatch, capsys):
    backend = pilot_backend()
    backend.on("GET", QUEUE_PATH, (500, error_body(500, "Workflow store request failed")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend)

    assert result.code == 1
    assert "error:" in result.err
    assert len(backend.sent("GET", QUEUE_PATH)) == 2


# Edge: 5xx or network error / timeout on `POST /runs` ... | one retry after a
#       backoff; a second failure makes that workflow's line `<slug> v<N> failed:
#       <reason>` ..., and the command exits 1
def test_a_run_report_that_fails_twice_is_a_failed_line_and_exit_1(monkeypatch, capsys):
    backend = pilot_backend()
    backend.on("POST", runs_path(), (503, error_body(503, "busy")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 1
    assert len(backend.sent("POST", runs_path())) == 2
    assert any(line.startswith(f"{SLUG} v1 failed: ") for line in result.lines)


# Edge: 4xx | not retried; the status and the backend's `message` are reported.
#       ... any other 4xx except 401/403 exits 1
def test_a_4xx_on_the_run_report_is_not_retried_and_exits_1(monkeypatch, capsys):
    backend = pilot_backend()
    backend.on("POST", runs_path(), (400, error_body(400, "steps must contain unique stepNumber")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 1
    assert len(backend.sent("POST", runs_path())) == 1
    assert "steps must contain unique stepNumber" in result.out + result.err


def test_a_4xx_other_than_404_on_the_fetch_exits_1(monkeypatch, capsys):
    backend = pilot_backend()
    backend.on("GET", detail_path(), (422, error_body(422, "Workflow is retired")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG], backend=backend)

    assert result.code == 1
    assert len(backend.sent("GET", detail_path())) == 1
    assert "Workflow is retired" in result.out + result.err


# Edge: A malformed backend response (wrong types, more than 50 steps, missing
#       `currentVersion`) | `error:` naming the field, nothing is run, exit 1
def test_a_malformed_detail_exits_1_naming_the_field_and_runs_nothing(monkeypatch, capsys):
    body = detail_json()
    del body["currentVersion"]
    backend = pilot_backend()
    backend.on("GET", detail_path(), (200, body))
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert "error:" in result.err and "currentVersion" in result.err
    assert executor.calls == []
    assert backend.sent("POST", runs_path()) == []


# Edge: A step with no target, a combobox/listbox/slider role, ... | the run
#       fails with `step N: <reason>`, nothing is launched, and a failed run
#       report is posted (that step `failed`, the others `unchecked`), exit 1
def test_an_unmappable_step_posts_a_failed_report_without_running(monkeypatch, capsys):
    steps = pilot_steps()
    steps[1]["target"]["role"] = "combobox"
    backend = pilot_backend(steps=steps)
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert executor.calls == []
    assert "step 2:" in result.out + result.err
    report = run_report(backend)
    assert report["result"] == "failed"
    assert {n: s["outcome"] for n, s in steps_by_number(report).items()} == {
        1: "unchecked", 2: "failed", 3: "unchecked",
    }
    assert backend.sent("POST", versions_path()) == []


# ── Versions that are not current ─────────────────────────────────────────────

# Story: `verify <slug> --version N`, where N is not the `currentVersion` the
#        fetch returns, sends only the token check and that `GET`: no run report
#        and no proposal. It prints `error: <slug> v<N> is not the current version
#        (v<M>); the backend serves only the current version's steps` to stderr
#        and exits 3.
def test_a_non_current_version_exits_3_after_only_the_token_check_and_the_get(
        monkeypatch, capsys):
    backend = pilot_backend(version=2)
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG, "--version", "1"],
                     backend=backend, executor=executor)

    assert result.code == 3
    assert (f"error: {SLUG} v1 is not the current version (v2); the backend serves only "
            "the current version's steps") in result.err
    assert backend.calls() == [("GET", QUEUE_PATH), ("GET", detail_path())]
    assert executor.calls == []


# Story: `--version` equal to the current version runs as if it were not given.
def test_the_current_version_named_with_version_runs_normally(monkeypatch, capsys):
    backend = pilot_backend(version=2)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG, "--version", "2"],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 0, result.err
    assert run_report(backend)["version"] == 2
    assert f"{SLUG} v2 passed" in result.lines


# Story: In `verify --all-unverified`, an entry whose version is not current
#        sends only its `GET`, nothing is posted for it, and it prints `<slug>
#        v<N> skipped: not the current version (v<M>)`.
# Story / map.md Decisions (ticket 01, option A): a skipped queue entry leaves
#        the exit code as the other entries make it (a queue of one skipped
#        entry exits 0).
def test_a_queue_entry_that_is_not_current_is_skipped_and_exits_0(monkeypatch, capsys):
    backend = FakeBackend()
    backend.on("GET", QUEUE_PATH, (200, [queue_item("old-flow", 1)]))
    backend.on("GET", detail_path("old-flow"), (200, detail_json("old-flow", version=2)))
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 0
    assert "old-flow v1 skipped: not the current version (v2)" in result.lines
    assert backend.calls() == [("GET", QUEUE_PATH), ("GET", detail_path("old-flow"))]
    assert executor.calls == []


# ── Walk the queue ────────────────────────────────────────────────────────────

def _queue_backend(entries, details=None):
    backend = FakeBackend()
    backend.on("GET", QUEUE_PATH, (200, entries))
    for entry in entries:
        slug = entry.get("slug")
        if isinstance(slug, str):
            body = (details or {}).get(slug, detail_json(slug, version=entry["version"]
                                                         if isinstance(entry.get("version"), int)
                                                         and entry["version"] >= 1 else 1))
            backend.on("GET", detail_path(slug), (200, body) if isinstance(body, dict) else body)
            backend.on("POST", runs_path(slug), (201, run_view(slug)))
    return backend


# Story: The command reads `GET /api/workflows/verification-queue` and runs every
#        entry, one at a time, in the order the backend returns them (oldest
#        first), with no cap. It prints one line per entry: `<slug> v<N> passed`,
#        `failed`, `healed` or `skipped`, with a reason after a colon when there is one.
def test_the_walk_runs_every_entry_in_queue_order_with_no_cap(monkeypatch, capsys):
    slugs = [f"flow-{i:02d}" for i in range(12)]
    backend = _queue_backend([queue_item(s, 1) for s in slugs])
    executor = StubExecutor(["pass"])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 0, result.err
    assert [line for line in result.lines if line.startswith("flow-")] == \
        [f"{s} v1 passed" for s in slugs]
    reported = [r.path for r in backend.requests if r.method == "POST"]
    assert reported == [runs_path(s) for s in slugs]
    assert len(backend.sent("GET", QUEUE_PATH)) == 1
    assert len(executor.calls) == 12


# Story: Exit 0 when every run passed (or the queue was empty), and exit 1 when
#        any run failed or was healed.
def test_an_empty_queue_exits_0(monkeypatch, capsys):
    backend = _queue_backend([])
    executor = StubExecutor()

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 0, result.err
    assert backend.calls() == [("GET", QUEUE_PATH)]
    assert executor.calls == []


def test_a_failed_entry_makes_the_walk_exit_1_and_the_walk_goes_on(monkeypatch, capsys):
    backend = _queue_backend([queue_item("first-flow", 1), queue_item("second-flow", 3)],
                             details={"second-flow": detail_json("second-flow", version=3)})
    executor = StubExecutor(["fail", "pass"])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert any(line.startswith("first-flow v1 failed") for line in result.lines)
    assert "second-flow v3 passed" in result.lines
    assert run_report(backend, "first-flow")["result"] == "failed"
    assert run_report(backend, "second-flow")["result"] == "passed"


def test_a_healed_entry_makes_the_walk_exit_1(monkeypatch, capsys):
    from bs_harness import HEALED_LINK, is_step

    backend = _queue_backend([queue_item(SLUG, 1)])
    backend.on("POST", versions_path(), (201, version_view(2, note="n", source="stepper")))
    world = engine_world(monkeypatch, broken=(2,),
                         direct=lambda s: {"css": HEALED_LINK} if is_step(2)(s) else None)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    assert any(line.startswith(f"{SLUG} v1 healed") for line in result.lines)


# Story: An entry that raises (a 5xx after the retry, a malformed detail) prints
#        as `failed` and the walk goes on to the next entry.
@pytest.mark.parametrize("problem", ["5xx", "malformed"])
def test_an_entry_that_raises_prints_failed_and_the_walk_goes_on(monkeypatch, capsys,
                                                                 problem):
    if problem == "5xx":
        broken = (503, error_body(503, "busy"))
    else:
        body = detail_json("first-flow")
        body["currentSteps"] = "not a list"
        broken = (200, body)
    backend = _queue_backend([queue_item("first-flow", 1), queue_item("second-flow", 1)])
    backend.on("GET", detail_path("first-flow"), broken)
    executor = StubExecutor(["pass"])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert any(line.startswith("first-flow v1 failed") for line in result.lines)
    assert "second-flow v1 passed" in result.lines
    assert backend.sent("POST", runs_path("first-flow")) == []


# Edge: 5xx ... on `POST /runs` ... in `--all-unverified` the walk goes on
def test_a_run_report_that_fails_twice_mid_walk_does_not_stop_it(monkeypatch, capsys):
    backend = _queue_backend([queue_item("first-flow", 1), queue_item("second-flow", 1)])
    backend.on("POST", runs_path("first-flow"), (502, error_body(502, "bad gateway")))

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=StubExecutor(["pass"]))

    assert result.code == 1
    assert any(line.startswith("first-flow v1 failed: ") for line in result.lines)
    assert "second-flow v1 passed" in result.lines


# Story: A malformed queue entry (a bad slug, a version that is not an integer
#        ≥ 1) prints as `? failed: entry <i>: <reason>`.
# Edge: A queue entry with a malformed slug or version | it is printed as `?
#       failed: entry <i>: <reason>`, the walk goes on, and the exit code is 1
@pytest.mark.parametrize("bad", [
    queue_item("Bad Slug!", 1),
    queue_item("zero-version", 0),
    {**queue_item("text-version", 1), "version": "1"},
], ids=["slug", "zero", "string"])
def test_a_malformed_queue_entry_prints_question_mark_failed_and_exits_1(monkeypatch, capsys,
                                                                         bad):
    backend = _queue_backend([queue_item("good-flow", 1)])
    backend.on("GET", QUEUE_PATH, (200, [bad, queue_item("good-flow", 1)]))
    executor = StubExecutor(["pass"])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", "--all-unverified"],
                     backend=backend, executor=executor)

    assert result.code == 1
    assert any(line.startswith("? failed: entry ") and line.count(":") >= 2
               for line in result.lines)
    assert "good-flow v1 passed" in result.lines


# ── The verify loop through its Python interface ──────────────────────────────

# Interfaces: `verify.verify_slug(client, executor, slug, *, version=None,
#             headless=True, check_token=True) -> VerifyOutcome` ... `VerifyOutcome`
#             has `slug`, `version`, `status`, `reason` and `proposed_version`.
async def test_verify_slug_returns_a_passed_outcome():
    from stepper.brightsky.verify import verify_slug

    backend = pilot_backend()
    outcome = await verify_slug(make_client(backend), StubExecutor(["pass"]), SLUG)

    assert outcome.slug == SLUG
    assert outcome.version == 1
    assert outcome.status == "passed"
    assert outcome.proposed_version is None
    assert backend.calls()[0] == ("GET", QUEUE_PATH)


async def test_verify_slug_without_check_token_skips_the_queue_read():
    from stepper.brightsky.verify import verify_slug

    backend = pilot_backend()
    outcome = await verify_slug(make_client(backend), StubExecutor(["pass"]), SLUG,
                                check_token=False)

    assert outcome.status == "passed"
    assert backend.calls() == [("GET", detail_path()), ("POST", runs_path())]


# Interfaces: A `BrightSkyHttpError` with status 401 or 403 from any call is never
#             turned into an outcome: it propagates (also out of `verify_all_unverified`).
async def test_a_401_propagates_out_of_verify_slug():
    from stepper.brightsky.client import BrightSkyHttpError
    from stepper.brightsky.verify import verify_slug

    backend = pilot_backend()
    backend.on("GET", QUEUE_PATH, (401, error_body(401, "Invalid bridge token")))

    with pytest.raises(BrightSkyHttpError):
        await verify_slug(make_client(backend), StubExecutor(), SLUG)


async def test_a_403_propagates_out_of_verify_all_unverified():
    from stepper.brightsky.client import BrightSkyHttpError
    from stepper.brightsky.verify import verify_all_unverified

    backend = _queue_backend([queue_item("first-flow", 1), queue_item("second-flow", 1)])
    backend.on("POST", runs_path("first-flow"), (403, error_body(403, "Token revoked")))

    with pytest.raises(BrightSkyHttpError):
        await verify_all_unverified(make_client(backend), StubExecutor(["pass"]))

    assert not any("second-flow" in r.path for r in backend.requests)


# Interfaces: `verify.verify_all_unverified(client, executor, *, headless=True) ->
#             QueueRun`, where `QueueRun` has `outcomes: list[VerifyOutcome]`, one
#             per queue entry in queue order.
async def test_verify_all_unverified_returns_one_outcome_per_entry_in_order():
    from stepper.brightsky.verify import verify_all_unverified

    backend = _queue_backend(
        [queue_item("first-flow", 1), queue_item("old-flow", 1), queue_item("third-flow", 1)],
        details={"old-flow": detail_json("old-flow", version=2)},
    )
    run = await verify_all_unverified(make_client(backend), StubExecutor(["fail", "pass"]))

    assert [(o.slug, o.version, o.status) for o in run.outcomes] == [
        ("first-flow", 1, "failed"), ("old-flow", 1, "skipped"), ("third-flow", 1, "passed"),
    ]
