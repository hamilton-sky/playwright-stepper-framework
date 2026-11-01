"""
Tests for the `brightsky verify` command in stepper/cli.py (ticket 07).

Every test drives `cli.run_cli` with a stub pipeline (`load_env`,
`_stepper_root`). The command reaches the network and the browser only through
`stepper.brightsky.verify.make_client` and `make_executor`, which are
monkeypatched here: the client runs over a recording transport and the
executor returns scripted `ExecutedStep`s. So the tests read what went over
the wire, what was printed, and the exit code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import stepper.brightsky.verify as verify
from stepper import cli
from stepper.brightsky.client import BrightSkyClient, HttpResponse
from stepper.brightsky.executor import ExecutedStep

TOKEN = "tok-SECRET-123"
URL = "https://bright-sky.example.com"
SLUG = "openlibrary-find-author"
QUEUE = "/api/workflows/verification-queue"


def detail_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}"


def runs_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}/runs"


def versions_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}/versions"


# ── doubles ───────────────────────────────────────────────────────────────────

@dataclass
class Sent:
    method: str
    path: str


class StubTransport:
    """Records every send; replays scripted responses per (method, path), the last repeating."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.sent: list[Sent] = []

    def on(self, method: str, path: str, *responses: tuple[int, object]) -> StubTransport:
        self.routes[(method, path)] = list(responses)
        return self

    def send(self, method, url, headers, body, timeout):
        path = urlsplit(url).path
        self.sent.append(Sent(method, path))
        script = self.routes.get((method, path))
        if not script:
            return HttpResponse(status=404, body=json.dumps(_error(404, "no route")).encode())
        status, payload = script.pop(0) if len(script) > 1 else script[0]
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return HttpResponse(status=status, body=raw)

    def calls(self) -> list[tuple[str, str]]:
        return [(s.method, s.path) for s in self.sent]


class FakeExecutor:
    """A StepExecutor that returns one scripted list of ExecutedSteps per call."""

    def __init__(self, *runs: list[ExecutedStep]) -> None:
        self._runs = list(runs)
        self.calls: list[bool] = []

    async def execute(self, mapped, *, headless):
        self.calls.append(headless)
        return self._runs.pop(0) if len(self._runs) > 1 else self._runs[0]


def _error(status: int, message: str) -> dict:
    return {"statusCode": status, "message": message, "error": "Error"}


def _step(title: str, role: str, name: str, url: str) -> dict:
    return {"title": title, "explanation": "", "expectedDomain": "openlibrary.org",
            "expectedUrl": url,
            "target": {"role": role, "accessibleName": name, "selectors": [],
                       "score": 0.8, "grounding": "current_page"}}


def _detail(slug: str = SLUG, version: int = 1) -> dict:
    return {"slug": slug, "site": "openlibrary.org",
            "currentVersion": {"version": version, "note": None},
            "currentSteps": [_step("Search for 'The Hobbit'", "textbox", "Search", "/"),
                             _step("Open the book page", "link", "The Hobbit", "/search"),
                             _step("Open the author page", "link", "J.R.R. Tolkien",
                                   "/works/")],
            "versions": [{"version": n, "note": None} for n in range(1, version + 1)]}


def _queue_item(slug: str, version: int = 1) -> dict:
    return {"slug": slug, "version": version, "stepperRuns": 0,
            "createdAt": "2026-10-01T00:00:00.000Z"}


def _backend(*, queue: list | None = None, version: int = 1) -> StubTransport:
    transport = StubTransport()
    transport.on("GET", QUEUE, (200, queue if queue is not None else []))
    transport.on("GET", detail_path(), (200, _detail(version=version)))
    transport.on("POST", runs_path(), (201, {"id": "run-1"}))
    transport.on("POST", versions_path(), (201, {"version": version + 1}))
    return transport


def passed(n: int) -> ExecutedStep:
    return ExecutedStep(n, "passed", True, "role")


def failed(n: int) -> ExecutedStep:
    return ExecutedStep(n, "failed", False, None, error="Element not found")


def unchecked(n: int) -> ExecutedStep:
    return ExecutedStep(n, "unchecked", False, None)


def healed(n: int) -> ExecutedStep:
    element = {"original": {"role": "link", "name": "The Hobbit"},
               "healed": {"role": "link", "name": "The Hobbit (1937)", "css": "a.result"},
               "tier": "embed_direct"}
    return ExecutedStep(n, "failed", False, "embed_direct", healed=True,
                        healed_element=element)


ALL_PASS = [passed(1), passed(2), passed(3)]


@dataclass
class Result:
    code: int
    out: str
    err: str
    clients: int
    executors: int

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()

    @property
    def text(self) -> str:
        return self.out + self.err


def run(monkeypatch, capsys, args: list[str], *, transport: StubTransport | None = None,
        executor: FakeExecutor | None = None, env: dict | None = None) -> Result:
    """`stepper brightsky ...` through run_cli, offline."""
    environ = {"BRIGHTSKY_API_URL": URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    if env is not None:
        environ = env
    for name in ("BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    transport = transport if transport is not None else _backend()
    executor = executor if executor is not None else FakeExecutor(ALL_PASS)
    clients: list[object] = []

    def fake_client(config):
        clients.append(config)
        return BrightSkyClient(config, transport=transport, sleep=lambda seconds: None)

    executors: list[object] = []

    def fake_executor():
        executors.append(executor)
        return executor

    monkeypatch.setattr(verify, "make_client", fake_client)
    monkeypatch.setattr(verify, "make_executor", fake_executor)

    pipeline = SimpleNamespace(load_env=lambda: None, _stepper_root=Path("."))
    capsys.readouterr()
    code = cli.run_cli(pipeline, argv=["brightsky", *args])
    out, err = capsys.readouterr()
    return Result(code=code, out=out, err=err, clients=len(clients),
                  executors=len(executors))


# ── config errors ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"])
def test_a_missing_variable_exits_3_with_no_traceback_and_no_client(monkeypatch, capsys,
                                                                    missing):
    env = {"BRIGHTSKY_API_URL": URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    del env[missing]
    transport = _backend()

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport, env=env)

    assert result.code == 3
    assert f"error: {missing} is not set" in result.err
    assert "Traceback" not in result.err
    assert result.clients == 0
    assert transport.sent == []


def test_a_config_error_does_not_print_the_token(monkeypatch, capsys):
    env = {"BRIGHTSKY_API_URL": "http://bright-sky.example.com",
           "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    transport = _backend()

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport, env=env)

    assert result.code == 3
    assert "error:" in result.err and "https" in result.err
    assert TOKEN not in result.text
    assert transport.sent == []


# ── usage errors ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args", [["verify", SLUG, "--all-unverified"], ["verify"]],
                         ids=["both", "neither"])
def test_both_or_neither_of_slug_and_all_unverified_exits_3(monkeypatch, capsys, args):
    transport = _backend()

    result = run(monkeypatch, capsys, args, transport=transport)

    assert result.code == 3
    assert result.err.startswith("error: ")
    assert transport.sent == []
    assert result.clients == 0


@pytest.mark.parametrize("value", ["x", "0", "-1", "1.5"])
def test_a_version_that_is_not_a_positive_integer_exits_3(monkeypatch, capsys, value):
    transport = _backend()

    result = run(monkeypatch, capsys, ["verify", SLUG, f"--version={value}"],
                 transport=transport)

    assert result.code == 3
    assert "error:" in result.err
    assert transport.sent == []


def test_version_with_all_unverified_exits_3(monkeypatch, capsys):
    transport = _backend()

    result = run(monkeypatch, capsys, ["verify", "--all-unverified", "--version", "1"],
                 transport=transport)

    assert result.code == 3
    assert "error:" in result.err
    assert transport.sent == []


def test_a_malformed_slug_exits_3_before_any_request(monkeypatch, capsys):
    transport = _backend()

    result = run(monkeypatch, capsys, ["verify", "Bad_Slug"], transport=transport)

    assert result.code == 3
    assert "error:" in result.err and "slug" in result.err
    assert transport.sent == []


def test_brightsky_with_no_subcommand_prints_help_and_succeeds(monkeypatch, capsys):
    pipeline = SimpleNamespace(load_env=lambda: None, _stepper_root=Path("."))

    assert cli.run_cli(pipeline, argv=["brightsky"]) == 0
    assert "verify" in capsys.readouterr().out


def test_verify_help_lists_all_unverified(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["brightsky", "verify", "--help"])
    assert exc.value.code == 0
    assert "--all-unverified" in capsys.readouterr().out


# ── HTTP errors ───────────────────────────────────────────────────────────────

def test_a_404_on_the_fetch_exits_3(monkeypatch, capsys):
    transport = _backend().on("GET", detail_path(), (404, _error(404, "Workflow not found")))
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport,
                 executor=executor)

    assert result.code == 3
    assert "error: HTTP 404: Workflow not found" in result.err
    assert executor.calls == []


def test_a_503_after_the_retry_exits_1_without_the_token(monkeypatch, capsys):
    transport = _backend().on("GET", detail_path(), (503, _error(503, "busy")))
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport,
                 executor=executor)

    assert result.code == 1
    assert "error: HTTP 503: busy" in result.err
    assert transport.calls().count(("GET", detail_path())) == 2
    assert executor.calls == []
    assert TOKEN not in result.text


def test_a_401_on_the_token_check_exits_3_with_one_request(monkeypatch, capsys):
    transport = _backend().on("GET", QUEUE, (401, _error(401, "Invalid bridge token")))

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 401): Invalid bridge token" in result.err
    assert transport.calls() == [("GET", QUEUE)]
    assert result.executors == 0
    assert TOKEN not in result.text


def test_a_403_on_the_run_report_exits_3(monkeypatch, capsys):
    transport = _backend().on("POST", runs_path(), (403, _error(403, "Token revoked")))

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 403): Token revoked" in result.err
    assert transport.calls().count(("POST", runs_path())) == 1


def test_a_401_on_the_proposal_exits_3(monkeypatch, capsys):
    transport = _backend().on("POST", versions_path(), (401, _error(401, "Token revoked")))
    executor = FakeExecutor([passed(1), healed(2), passed(3)])

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport,
                 executor=executor)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 401): Token revoked" in result.err
    assert transport.calls().count(("POST", versions_path())) == 1


def test_a_malformed_response_exits_1_naming_the_field(monkeypatch, capsys):
    body = _detail()
    del body["currentVersion"]
    transport = _backend().on("GET", detail_path(), (200, body))
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG], transport=transport,
                 executor=executor)

    assert result.code == 1
    assert result.err.startswith("error: ") and "currentVersion" in result.err
    assert executor.calls == []
    assert TOKEN not in result.text


# ── outcomes ──────────────────────────────────────────────────────────────────

def test_a_passed_run_exits_0(monkeypatch, capsys):
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG], executor=executor)

    assert result.code == 0, result.err
    assert result.lines == [f"{SLUG} v1 passed"]
    assert executor.calls == [True]


def test_show_runs_headed(monkeypatch, capsys):
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG, "--show"], executor=executor)

    assert result.code == 0, result.err
    assert executor.calls == [False]


def test_a_failed_run_exits_1_with_its_reason(monkeypatch, capsys):
    executor = FakeExecutor([passed(1), failed(2), unchecked(3)])

    result = run(monkeypatch, capsys, ["verify", SLUG], executor=executor)

    assert result.code == 1
    assert result.lines == [f"{SLUG} v1 failed: step 2: Element not found"]


def test_a_healed_run_exits_1_and_names_the_proposal(monkeypatch, capsys):
    executor = FakeExecutor([passed(1), healed(2), passed(3)])

    result = run(monkeypatch, capsys, ["verify", SLUG], executor=executor)

    assert result.code == 1
    assert result.lines == [f"{SLUG} v1 healed -> proposed v2"]


def test_the_current_version_named_with_version_runs(monkeypatch, capsys):
    result = run(monkeypatch, capsys, ["verify", SLUG, "--version", "1"])

    assert result.code == 0, result.err
    assert result.lines == [f"{SLUG} v1 passed"]


def test_a_version_that_is_not_current_exits_3(monkeypatch, capsys):
    transport = _backend(version=1)
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", SLUG, "--version", "2"],
                 transport=transport, executor=executor)

    assert result.code == 3
    assert (f"error: {SLUG} v2 is not the current version (v1); the backend serves only "
            "the current version's steps") in result.err
    assert transport.calls() == [("GET", QUEUE), ("GET", detail_path())]
    assert executor.calls == []
    assert result.out == ""


# ── the queue walk ────────────────────────────────────────────────────────────

def test_an_empty_queue_exits_0(monkeypatch, capsys):
    transport = _backend(queue=[])

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport)

    assert result.code == 0, result.err
    assert result.out == ""
    assert transport.calls() == [("GET", QUEUE)]


def test_a_passed_and_a_failed_entry_print_in_queue_order_and_exit_1(monkeypatch, capsys):
    transport = _backend(queue=[_queue_item("first-flow", 1), _queue_item("second-flow", 3)])
    for slug, version in (("first-flow", 1), ("second-flow", 3)):
        transport.on("GET", detail_path(slug), (200, _detail(slug, version)))
        transport.on("POST", runs_path(slug), (201, {"id": "run"}))
    executor = FakeExecutor(ALL_PASS, [passed(1), failed(2), unchecked(3)])

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport,
                 executor=executor)

    assert result.code == 1
    assert result.lines == ["first-flow v1 passed",
                            "second-flow v3 failed: step 2: Element not found"]


def test_a_queue_of_only_a_non_current_entry_is_skipped_and_exits_0(monkeypatch, capsys):
    # Ticket 01, option A: a skipped entry leaves the exit code alone.
    transport = _backend(queue=[_queue_item("old-flow", 1)])
    transport.on("GET", detail_path("old-flow"), (200, _detail("old-flow", 2)))
    executor = FakeExecutor(ALL_PASS)

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport,
                 executor=executor)

    assert result.code == 0, result.err
    assert result.lines == ["old-flow v1 skipped: not the current version (v2)"]
    assert executor.calls == []


def test_a_malformed_queue_entry_prints_question_mark_failed(monkeypatch, capsys):
    transport = _backend(queue=[_queue_item("Bad Slug!", 1), _queue_item(SLUG, 1)])

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport)

    assert result.code == 1
    assert result.lines[0].startswith("? failed: entry 1: ")
    assert result.lines[1] == f"{SLUG} v1 passed"


def test_a_401_on_the_queue_read_exits_3(monkeypatch, capsys):
    transport = _backend().on("GET", QUEUE, (401, _error(401, "Invalid bridge token")))

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport)

    assert result.code == 3
    assert "error: bridge token rejected (HTTP 401): Invalid bridge token" in result.err
    assert TOKEN not in result.text


def test_a_503_on_the_queue_read_exits_1(monkeypatch, capsys):
    transport = _backend().on("GET", QUEUE, (503, _error(503, "busy")))

    result = run(monkeypatch, capsys, ["verify", "--all-unverified"], transport=transport)

    assert result.code == 1
    assert "error: HTTP 503: busy" in result.err
    assert TOKEN not in result.text
