"""
Tests for stepper/brightsky/verify.py (ticket 06): the verify loop.

`verify_slug` checks the token, fetches, maps, runs, reports and proposes;
`verify_all_unverified` walks the queue. Here the executor is a fake that
returns scripted `ExecutedStep`s, and the client runs over a recording
transport, so every assertion reads what went over the wire.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest

from stepper.brightsky.client import BrightSkyClient, BrightSkyHttpError, HttpResponse
from stepper.brightsky.config import BrightSkyConfig
from stepper.brightsky.executor import ExecutedStep, PipelineExecutor
from stepper.brightsky.verify import (
    QueueRun,
    VerifyOutcome,
    make_client,
    make_executor,
    verify_all_unverified,
    verify_slug,
)

TOKEN = "bst_verify_secret_token_3a7c1f"
URL = "https://bright-sky.example.com"
SLUG = "openlibrary-find-author"
QUEUE = "/api/workflows/verification-queue"

STORED = {"role": "link", "name": "The Hobbit"}
FOUND = {"role": "link", "name": "The Hobbit (1937)", "css": "a.result"}


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
    body: dict | None


class StubTransport:
    """Records every send; replays scripted responses per (method, path), the last repeating."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.sent: list[Sent] = []

    def on(self, method: str, path: str, *responses: object) -> StubTransport:
        self.routes[(method, path)] = list(responses)
        return self

    def send(self, method, url, headers, body, timeout):
        path = urlsplit(url).path
        self.sent.append(Sent(method, path, json.loads(body) if body else None))
        script = self.routes.get((method, path))
        if not script:
            return HttpResponse(status=404, body=json.dumps(_error(404, "no route")).encode())
        response = script.pop(0) if len(script) > 1 else script[0]
        status, payload = response
        return HttpResponse(status=status, body=json.dumps(payload).encode())

    def calls(self) -> list[tuple[str, str]]:
        return [(s.method, s.path) for s in self.sent]

    def bodies(self, method: str, path: str) -> list[dict]:
        return [s.body for s in self.sent if s.method == method and s.path == path]


class FakeExecutor:
    """A StepExecutor that returns one scripted list of ExecutedSteps per call."""

    def __init__(self, *runs: list[ExecutedStep]) -> None:
        self._runs = list(runs)
        self.calls: list[dict] = []

    async def execute(self, mapped, *, headless):
        self.calls.append({"mapped": mapped, "headless": headless})
        return self._runs.pop(0) if len(self._runs) > 1 else self._runs[0]


def _error(status: int, message: str) -> dict:
    return {"statusCode": status, "message": message, "error": "Error"}


def _step(title: str, role: str, name: str, url: str) -> dict:
    return {"title": title, "explanation": "", "expectedDomain": "openlibrary.org",
            "expectedUrl": url,
            "target": {"role": role, "accessibleName": name, "selectors": [],
                       "score": 0.8, "grounding": "current_page"}}


def _steps() -> list[dict]:
    return [_step("Search for 'The Hobbit'", "textbox", "Search", "/"),
            _step("Open the book page", "link", "The Hobbit", "/search"),
            _step("Open the author page", "link", "J.R.R. Tolkien", "/works/")]


def _detail(slug: str = SLUG, version: int = 1, steps: list[dict] | None = None) -> dict:
    return {"slug": slug, "site": "openlibrary.org",
            "currentVersion": {"version": version, "note": None},
            "currentSteps": steps if steps is not None else _steps(),
            "versions": [{"version": n, "note": None} for n in range(1, version + 1)]}


def _queue_item(slug: str, version: int = 1) -> dict:
    return {"slug": slug, "version": version, "stepperRuns": 0,
            "createdAt": "2026-10-01T00:00:00.000Z"}


def _backend(*, queue: list | None = None, version: int = 1,
             steps: list[dict] | None = None) -> StubTransport:
    transport = StubTransport()
    transport.on("GET", QUEUE, (200, queue if queue is not None else []))
    transport.on("GET", detail_path(), (200, _detail(version=version, steps=steps)))
    transport.on("POST", runs_path(), (201, {"id": "run-1"}))
    transport.on("POST", versions_path(), (201, {"version": version + 1}))
    return transport


def _client(transport: StubTransport) -> BrightSkyClient:
    return BrightSkyClient(BrightSkyConfig(api_url=URL, token=TOKEN),
                           transport=transport, sleep=lambda seconds: None)


def passed(n: int) -> ExecutedStep:
    return ExecutedStep(n, "passed", True, "role")


def failed(n: int) -> ExecutedStep:
    return ExecutedStep(n, "failed", False, None, error="Element not found → none")


def unchecked(n: int) -> ExecutedStep:
    return ExecutedStep(n, "unchecked", False, None)


def healed(n: int, element: dict | None = None, tier: str = "embed_direct") -> ExecutedStep:
    healed_element = None if element is None else {
        "original": dict(STORED), "healed": dict(element), "tier": tier}
    return ExecutedStep(n, "failed", False, tier, healed=True,
                        healed_element=healed_element)


def _by_number(report: dict) -> dict[int, dict]:
    return {s["stepNumber"]: s for s in report["steps"]}


# ── one workflow ──────────────────────────────────────────────────────────────

async def test_a_full_pass_posts_one_passed_report_with_one_key_and_no_proposal():
    transport = _backend()
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert transport.calls() == [("GET", QUEUE), ("GET", detail_path()),
                                 ("POST", runs_path())]
    [report] = transport.bodies("POST", runs_path())
    assert report["result"] == "passed"
    assert report["version"] == 1
    assert report["client"] == "stepper"
    assert [s["stepNumber"] for s in report["steps"]] == [1, 2, 3]
    for step in report["steps"]:
        assert step["outcome"] == "passed"
        assert step["matched"] is True
        assert isinstance(step["tier"], str) and step["tier"]
    assert isinstance(report["idempotencyKey"], str) and report["idempotencyKey"]
    assert transport.bodies("POST", versions_path()) == []
    assert outcome == VerifyOutcome(slug=SLUG, version=1, status="passed", reason="",
                                    proposed_version=None)
    assert executor.calls[0]["headless"] is True


async def test_each_run_gets_its_own_idempotency_key():
    transport = _backend()
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    await verify_slug(_client(transport), executor, SLUG)
    await verify_slug(_client(transport), executor, SLUG)

    first, second = transport.bodies("POST", runs_path())
    assert first["idempotencyKey"] != second["idempotencyKey"]


async def test_a_failed_step_reports_failed_with_later_steps_unchecked_and_proposes_nothing():
    transport = _backend()
    executor = FakeExecutor([passed(1), failed(2), unchecked(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    [report] = transport.bodies("POST", runs_path())
    assert report["result"] == "failed"
    steps = _by_number(report)
    assert steps[2]["outcome"] == "failed"
    assert steps[3]["outcome"] == "unchecked"
    assert transport.bodies("POST", versions_path()) == []
    assert outcome.status == "failed"
    assert outcome.proposed_version is None


async def test_an_unmappable_step_posts_a_failed_report_and_executes_nothing():
    steps = _steps()
    steps[1]["target"]["role"] = "combobox"
    transport = _backend(steps=steps)
    executor = FakeExecutor([passed(1)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert executor.calls == []
    [report] = transport.bodies("POST", runs_path())
    assert report["result"] == "failed"
    by_number = _by_number(report)
    assert by_number[2] == {"stepNumber": 2, "matched": False, "tier": "unmapped",
                            "outcome": "failed"}
    assert by_number[1]["outcome"] == "unchecked"
    assert by_number[3]["outcome"] == "unchecked"
    assert outcome.status == "failed"
    assert outcome.reason.startswith("step 2: ")
    assert transport.bodies("POST", versions_path()) == []


async def test_a_heal_plus_a_later_failure_proposes_nothing():
    transport = _backend()
    executor = FakeExecutor([passed(1), healed(2, FOUND), failed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    [report] = transport.bodies("POST", runs_path())
    assert report["result"] == "failed"
    assert _by_number(report)[2]["outcome"] == "failed"
    assert transport.bodies("POST", versions_path()) == []
    assert outcome.status == "failed"
    assert outcome.proposed_version is None


async def test_a_heal_with_every_other_step_passed_is_reported_then_proposed():
    transport = _backend()
    executor = FakeExecutor([passed(1), healed(2, FOUND), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert [c for c in transport.calls() if c[0] == "POST"] == [
        ("POST", runs_path()), ("POST", versions_path())]
    [report] = transport.bodies("POST", runs_path())
    assert report["result"] == "failed"
    assert _by_number(report)[2] == {"stepNumber": 2, "matched": False,
                                     "tier": "embed_direct", "outcome": "failed"}
    [proposal] = transport.bodies("POST", versions_path())
    assert proposal["source"] == "stepper"
    fetched = _steps()
    assert proposal["steps"][0] == fetched[0]
    assert proposal["steps"][2] == fetched[2]
    assert proposal["steps"][1]["target"] == {
        "role": "link", "accessibleName": "The Hobbit (1937)", "selectors": ["a.result"],
        "score": 0.8, "grounding": "current_page"}
    assert {k: v for k, v in proposal["steps"][1].items() if k != "target"} == \
        {k: v for k, v in fetched[1].items() if k != "target"}
    assert report["idempotencyKey"] in proposal["note"]
    assert "v1" in proposal["note"] and "step 2" in proposal["note"]
    assert outcome == VerifyOutcome(slug=SLUG, version=1, status="healed", reason="",
                                    proposed_version=2)


@pytest.mark.parametrize("tier, source", [
    ("embed_direct", "stepper"), ("heal_cache", "stepper"),
    ("cheap", "haiku"), ("big", "haiku"), ("healer", "haiku"),
])
async def test_the_proposal_source_follows_the_healed_tiers(tier, source):
    transport = _backend()
    executor = FakeExecutor([passed(1), healed(2, FOUND, tier=tier), passed(3)])

    await verify_slug(_client(transport), executor, SLUG)

    [proposal] = transport.bodies("POST", versions_path())
    assert proposal["source"] == source


async def test_one_ai_heal_among_free_heals_makes_the_source_haiku():
    transport = _backend()
    executor = FakeExecutor([healed(1, {"placeholder": "Search"}),
                             healed(2, FOUND, tier="cheap"), passed(3)])

    await verify_slug(_client(transport), executor, SLUG)

    [proposal] = transport.bodies("POST", versions_path())
    assert proposal["source"] == "haiku"
    assert proposal["steps"][0]["target"]["role"] == "textbox"
    assert "step 1" in proposal["note"] and "step 2" in proposal["note"]


async def test_a_heal_by_injection_is_not_proposed_and_says_why():
    transport = _backend()
    executor = FakeExecutor([passed(1), healed(2, None), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert transport.bodies("POST", versions_path()) == []
    assert outcome.status == "healed"
    assert outcome.proposed_version is None
    assert "step 2" in outcome.reason


async def test_a_healed_element_the_store_cannot_describe_is_not_proposed():
    transport = _backend()
    executor = FakeExecutor([passed(1), healed(2, {"text": "The Hobbit"}), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert transport.bodies("POST", versions_path()) == []
    assert outcome.status == "healed"
    assert "describe" in outcome.reason


async def test_a_failed_propose_leaves_the_status_healed_with_the_reason():
    transport = _backend()
    transport.on("POST", versions_path(), (400, _error(400, "steps are invalid")))
    executor = FakeExecutor([passed(1), healed(2, FOUND), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert outcome.status == "healed"
    assert outcome.proposed_version is None
    assert outcome.reason.startswith("proposal failed: ")
    assert "steps are invalid" in outcome.reason


async def test_a_failed_report_is_a_failed_outcome_and_skips_the_propose():
    transport = _backend()
    transport.on("POST", runs_path(), (503, _error(503, "busy")))
    executor = FakeExecutor([passed(1), healed(2, FOUND), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG)

    assert len(transport.bodies("POST", runs_path())) == 2
    assert transport.bodies("POST", versions_path()) == []
    assert outcome.status == "failed"
    assert "busy" in outcome.reason


async def test_a_non_current_version_is_skipped_after_only_the_token_check_and_the_get():
    transport = _backend(version=2)
    executor = FakeExecutor([passed(1)])

    outcome = await verify_slug(_client(transport), executor, SLUG, version=1)

    assert transport.calls() == [("GET", QUEUE), ("GET", detail_path())]
    assert executor.calls == []
    assert outcome == VerifyOutcome(slug=SLUG, version=1, status="skipped",
                                    reason="not the current version (v2)",
                                    proposed_version=None)


async def test_the_current_version_given_explicitly_runs_as_usual():
    transport = _backend(version=2)
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    outcome = await verify_slug(_client(transport), executor, SLUG, version=2,
                                headless=False)

    assert outcome.status == "passed"
    assert transport.bodies("POST", runs_path())[0]["version"] == 2
    assert executor.calls[0]["headless"] is False


async def test_without_check_token_the_queue_is_not_read():
    transport = _backend()

    await verify_slug(_client(transport), FakeExecutor([passed(1), passed(2), passed(3)]),
                      SLUG, check_token=False)

    assert transport.calls() == [("GET", detail_path()), ("POST", runs_path())]


# ── a rejected token ──────────────────────────────────────────────────────────

async def test_a_401_on_the_token_check_raises_after_one_request_and_runs_nothing():
    transport = _backend()
    transport.on("GET", QUEUE, (401, _error(401, "Invalid bridge token")))
    executor = FakeExecutor([passed(1)])

    with pytest.raises(BrightSkyHttpError) as raised:
        await verify_slug(_client(transport), executor, SLUG)

    assert raised.value.status == 401
    assert transport.calls() == [("GET", QUEUE)]
    assert executor.calls == []


async def test_a_403_on_the_run_report_raises_after_the_run():
    transport = _backend()
    transport.on("POST", runs_path(), (403, _error(403, "Token revoked")))
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    with pytest.raises(BrightSkyHttpError) as raised:
        await verify_slug(_client(transport), executor, SLUG)

    assert raised.value.status == 403
    assert len(executor.calls) == 1
    assert transport.calls()[-1] == ("POST", runs_path())


async def test_a_401_on_the_propose_raises():
    transport = _backend()
    transport.on("POST", versions_path(), (401, _error(401, "Token revoked")))
    executor = FakeExecutor([passed(1), healed(2, FOUND), passed(3)])

    with pytest.raises(BrightSkyHttpError) as raised:
        await verify_slug(_client(transport), executor, SLUG)

    assert raised.value.status == 401


async def test_a_403_on_an_unmappable_steps_report_raises():
    steps = _steps()
    steps[0]["target"] = None
    transport = _backend(steps=steps)
    transport.on("POST", runs_path(), (403, _error(403, "Token revoked")))

    with pytest.raises(BrightSkyHttpError):
        await verify_slug(_client(transport), FakeExecutor([passed(1)]), SLUG)


# ── the queue walk ────────────────────────────────────────────────────────────

def _queue_backend(entries: list[dict], versions: dict[str, int] | None = None) -> StubTransport:
    transport = StubTransport()
    transport.on("GET", QUEUE, (200, entries))
    for entry in entries:
        slug = entry["slug"]
        current = (versions or {}).get(slug, entry["version"])
        transport.on("GET", detail_path(slug), (200, _detail(slug, version=current)))
        transport.on("POST", runs_path(slug), (201, {"id": "run"}))
    return transport


async def test_the_walk_runs_all_12_entries_in_queue_order():
    slugs = [f"flow-{i:02d}" for i in range(12)]
    transport = _queue_backend([_queue_item(s) for s in slugs])
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    run = await verify_all_unverified(_client(transport), executor)

    assert isinstance(run, QueueRun)
    assert [(o.slug, o.status) for o in run.outcomes] == [(s, "passed") for s in slugs]
    assert len(executor.calls) == 12
    assert [p for m, p in transport.calls() if m == "POST"] == [runs_path(s) for s in slugs]
    assert transport.calls().count(("GET", QUEUE)) == 1


async def test_one_entry_raising_a_503_does_not_stop_the_next():
    transport = _queue_backend([_queue_item("first-flow"), _queue_item("second-flow")])
    transport.on("GET", detail_path("first-flow"), (503, _error(503, "busy")))
    executor = FakeExecutor([passed(1), passed(2), passed(3)])

    run = await verify_all_unverified(_client(transport), executor)

    first, second = run.outcomes
    assert (first.slug, first.version, first.status) == ("first-flow", 1, "failed")
    assert "503" in first.reason
    assert (second.slug, second.status) == ("second-flow", "passed")
    assert transport.bodies("POST", runs_path("first-flow")) == []


async def test_a_malformed_detail_is_a_failed_entry_and_the_walk_goes_on():
    transport = _queue_backend([_queue_item("first-flow"), _queue_item("second-flow")])
    transport.on("GET", detail_path("first-flow"), (200, {"slug": "first-flow"}))

    run = await verify_all_unverified(
        _client(transport), FakeExecutor([passed(1), passed(2), passed(3)]))

    assert [o.status for o in run.outcomes] == ["failed", "passed"]


async def test_a_rejected_queue_entry_is_a_failed_question_mark_outcome():
    transport = _queue_backend([_queue_item("good-flow")])
    transport.on("GET", QUEUE, (200, [_queue_item("Bad Slug!"), _queue_item("good-flow")]))

    run = await verify_all_unverified(
        _client(transport), FakeExecutor([passed(1), passed(2), passed(3)]))

    bad, good = run.outcomes
    assert (bad.slug, bad.status, bad.version) == ("?", "failed", None)
    assert bad.reason.startswith("entry 1: ")
    assert (good.slug, good.status) == ("good-flow", "passed")


async def test_a_non_current_queue_entry_is_skipped_and_posts_nothing():
    transport = _queue_backend([_queue_item("old-flow", 1)], versions={"old-flow": 2})
    executor = FakeExecutor([passed(1)])

    run = await verify_all_unverified(_client(transport), executor)

    [outcome] = run.outcomes
    assert (outcome.slug, outcome.version, outcome.status) == ("old-flow", 1, "skipped")
    assert transport.calls() == [("GET", QUEUE), ("GET", detail_path("old-flow"))]
    assert executor.calls == []


async def test_a_401_on_the_first_entrys_report_stops_the_walk():
    transport = _queue_backend([_queue_item("first-flow"), _queue_item("second-flow")])
    transport.on("POST", runs_path("first-flow"), (401, _error(401, "Token revoked")))

    with pytest.raises(BrightSkyHttpError) as raised:
        await verify_all_unverified(
            _client(transport), FakeExecutor([passed(1), passed(2), passed(3)]))

    assert raised.value.status == 401
    assert not any("second-flow" in path for _, path in transport.calls())


async def test_an_empty_queue_is_an_empty_run():
    transport = _queue_backend([])

    run = await verify_all_unverified(_client(transport), FakeExecutor([passed(1)]))

    assert run == QueueRun(outcomes=[])
    assert transport.calls() == [("GET", QUEUE)]


# ── the seams the CLI uses ────────────────────────────────────────────────────

def test_make_executor_gives_a_pipeline_executor():
    assert isinstance(make_executor(), PipelineExecutor)


def test_make_client_gives_a_client_for_the_config():
    assert isinstance(make_client(BrightSkyConfig(api_url=URL, token=TOKEN)), BrightSkyClient)
