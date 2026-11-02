"""
brightsky-verify acceptance: config.load_config and client.BrightSkyClient.

Source: spec.md, Interfaces (Environment, Python) and the Edge cases table.
"""
from __future__ import annotations

import pytest

from bs_harness import (
    API_URL,
    QUEUE_PATH,
    SLUG,
    TOKEN,
    FakeBackend,
    detail_json,
    detail_path,
    error_body,
    make_client,
    pilot_steps,
    queue_item,
    version_view,
    versions_path,
)


def _config_error():
    from stepper.brightsky.config import BrightSkyConfigError

    return BrightSkyConfigError


# Edge: `BRIGHTSKY_API_URL` or `BRIGHTSKY_BRIDGE_TOKEN` missing or blank |
#       `error: <NAME> is not set`, no request, exit 3
@pytest.mark.parametrize("missing", ["BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"])
@pytest.mark.parametrize("blank", [False, True])
def test_load_config_names_the_missing_or_blank_variable(missing, blank):
    from stepper.brightsky.config import load_config

    environ = {"BRIGHTSKY_API_URL": API_URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    if blank:
        environ[missing] = "   "
    else:
        del environ[missing]

    with pytest.raises(_config_error()) as caught:
        load_config(environ)

    assert f"{missing} is not set" in str(caught.value)


# Interfaces: `config.load_config(environ) -> BrightSkyConfig` (frozen dataclass:
#             `api_url`, `token`). A trailing `/` is ignored.
def test_load_config_reads_both_variables_into_a_frozen_config():
    import dataclasses

    from stepper.brightsky.config import load_config

    config = load_config({"BRIGHTSKY_API_URL": API_URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN})

    assert config.token == TOKEN
    assert config.api_url.rstrip("/") == API_URL
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.token = "other"  # type: ignore[misc]


# Edge: `BRIGHTSKY_API_URL` is `http://` to a non-loopback host, or not http(s) |
#       `error:` saying the token is only sent over https (http is allowed for
#       localhost, 127.0.0.1 and ::1), exit 3
@pytest.mark.parametrize("url", [
    "http://bright-sky.example.com",
    "http://10.0.0.5:3001",
    "ftp://bright-sky.example.com",
    "file:///etc/passwd",
])
def test_the_token_is_only_sent_over_https_or_to_loopback(url):
    from stepper.brightsky.config import load_config

    with pytest.raises(_config_error()) as caught:
        load_config({"BRIGHTSKY_API_URL": url, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN})

    message = str(caught.value)
    assert "https" in message
    assert TOKEN not in message


@pytest.mark.parametrize("url", [
    "https://bright-sky.example.com",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://[::1]:3001",
])
def test_https_anywhere_and_http_to_loopback_are_accepted(url):
    from stepper.brightsky.config import load_config

    config = load_config({"BRIGHTSKY_API_URL": url, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN})

    assert config.api_url.rstrip("/") == url


# Interfaces: A trailing `/` is ignored. `BRIGHTSKY_BRIDGE_TOKEN`: sent as
#             `Authorization: Bearer <token>`.
def test_requests_go_to_the_base_url_with_the_bearer_token():
    backend = FakeBackend().on("GET", QUEUE_PATH, (200, []))
    client = make_client(backend, url=API_URL + "/")

    items, reasons = client.queue()

    assert (items, reasons) == ([], [])
    assert len(backend.requests) == 1
    assert backend.requests[0].url == API_URL + QUEUE_PATH
    assert backend.requests[0].headers.get("authorization") == f"Bearer {TOKEN}"


# Bar: a 5xx is retried once and a 4xx is not.
# Edge: 5xx or network error / timeout on the token check, the queue read or the
#       fetch | one retry after a backoff
def test_a_5xx_is_retried_once_after_a_backoff_and_then_succeeds():
    sleeps: list = []
    backend = FakeBackend().on(
        "GET", detail_path(),
        (503, error_body(503, "busy")),
        (200, detail_json()),
    )
    client = make_client(backend, sleeps=sleeps)

    detail = client.get_workflow(SLUG)

    assert detail.current_version == 1
    assert len(backend.sent("GET", detail_path())) == 2
    assert len(sleeps) == 1 and sleeps[0] > 0


def test_a_second_5xx_raises_brightsky_http_error_after_exactly_one_retry():
    from stepper.brightsky.client import BrightSkyHttpError

    backend = FakeBackend().on("GET", detail_path(), (502, error_body(502, "bad gateway")))
    client = make_client(backend)

    with pytest.raises(BrightSkyHttpError) as caught:
        client.get_workflow(SLUG)

    assert len(backend.sent("GET", detail_path())) == 2
    assert "502" in str(caught.value) or getattr(caught.value, "status", None) == 502


# Edge: 4xx | not retried; the status and the backend's `message` are reported.
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_a_4xx_is_not_retried_and_carries_the_status_and_message(status):
    from stepper.brightsky.client import BrightSkyHttpError

    sleeps: list = []
    backend = FakeBackend().on("GET", detail_path(),
                               (status, error_body(status, "the backend said no")))
    client = make_client(backend, sleeps=sleeps)

    with pytest.raises(BrightSkyHttpError) as caught:
        client.get_workflow(SLUG)

    assert len(backend.requests) == 1
    assert sleeps == []
    assert getattr(caught.value, "status", None) == status
    assert "the backend said no" in str(caught.value) or \
        getattr(caught.value, "message", None) == "the backend said no"


# Edge: 5xx or network error / timeout ... | one retry after a backoff
@pytest.mark.parametrize("failure", [OSError("connection refused"), TimeoutError("timed out")])
def test_a_network_error_is_retried_once(failure):
    backend = FakeBackend().on("GET", QUEUE_PATH, failure, (200, [queue_item(SLUG, 1)]))
    client = make_client(backend)

    items, reasons = client.queue()

    assert [(i.slug, i.version) for i in items] == [(SLUG, 1)]
    assert reasons == []
    assert len(backend.requests) == 2


def test_a_second_network_error_raises_after_one_retry():
    backend = FakeBackend().on("GET", QUEUE_PATH, OSError("connection refused"))
    client = make_client(backend)

    with pytest.raises(Exception):
        client.queue()

    assert len(backend.requests) == 2


# Edge: A malformed backend response (wrong types, more than 50 steps, missing
#       `currentVersion`) | `error:` naming the field, nothing is run, exit 1
def _without_current_version():
    body = detail_json()
    del body["currentVersion"]
    return body, "currentVersion"


def _version_as_string():
    body = detail_json()
    body["currentVersion"]["version"] = "1"
    return body, "version"


def _too_many_steps():
    step = pilot_steps()[1]
    return detail_json(steps=[dict(step) for _ in range(51)]), "steps"


def _steps_not_a_list():
    body = detail_json()
    body["currentSteps"] = {"0": pilot_steps()[0]}
    return body, "steps"


@pytest.mark.parametrize("make_body", [
    _without_current_version, _version_as_string, _too_many_steps, _steps_not_a_list,
])
def test_a_malformed_detail_raises_a_response_error_naming_the_field(make_body):
    from stepper.brightsky.client import BrightSkyResponseError

    body, field_name = make_body()
    backend = FakeBackend().on("GET", detail_path(), (200, body))
    client = make_client(backend)

    with pytest.raises(BrightSkyResponseError) as caught:
        client.get_workflow(SLUG)

    assert field_name in str(caught.value)


# Interfaces: `get_workflow(slug) -> WorkflowDetail` with slug, site,
#             current_version, steps (the validated wire dicts) and versions
#             (each version's number and note).
def test_get_workflow_keeps_the_wire_steps_and_the_version_notes():
    versions = [version_view(1, note="Pilot seed"), version_view(2, note="healed run k")]
    backend = FakeBackend().on("GET", detail_path(),
                               (200, detail_json(version=2, versions=versions)))
    client = make_client(backend)

    detail = client.get_workflow(SLUG)

    assert detail.slug == SLUG
    assert detail.site == "openlibrary.org"
    assert detail.current_version == 2
    assert detail.steps == pilot_steps()
    assert list(detail.versions) == [(1, "Pilot seed"), (2, "healed run k")]


# Interfaces: `queue() -> tuple[list[QueueItem], list[str]]`: the valid entries
#             in the backend's order, and one reason for each malformed entry,
#             which is left out.
def test_queue_keeps_valid_entries_in_order_and_gives_a_reason_per_malformed_one():
    bad_slug = queue_item("Not A Slug!", 1)
    zero_version = queue_item("zero-version", 0)
    string_version = queue_item("string-version", 1)
    string_version["version"] = "1"
    backend = FakeBackend().on("GET", QUEUE_PATH, (200, [
        queue_item("first-flow", 1, runs=0, created="2026-09-01T00:00:00.000Z"),
        bad_slug,
        queue_item("second-flow", 4, runs=1, created="2026-09-02T00:00:00.000Z"),
        zero_version,
        string_version,
    ]))
    client = make_client(backend)

    items, reasons = client.queue()

    assert [(i.slug, i.version) for i in items] == [("first-flow", 1), ("second-flow", 4)]
    assert items[1].stepper_runs == 1
    assert items[0].created_at
    assert len(reasons) == 3
    assert all(isinstance(r, str) and r for r in reasons)


# Interfaces: `propose_version(slug, proposal: Proposal) -> int`, the new version number
def test_propose_version_posts_the_proposal_and_returns_the_new_version():
    from stepper.brightsky.models import Proposal

    backend = FakeBackend().on("POST", versions_path(),
                               (201, version_view(2, note="n", source="stepper")))
    client = make_client(backend)

    number = client.propose_version(SLUG, Proposal(steps=pilot_steps(), source="stepper",
                                                   note="healed in run key-1"))

    assert number == 2
    sent = backend.sent("POST", versions_path())
    assert len(sent) == 1
    assert sent[0].body == {"steps": pilot_steps(), "source": "stepper",
                            "note": "healed in run key-1"}
    assert sent[0].headers.get("authorization") == f"Bearer {TOKEN}"


# Edge: A propose POST failed with a 5xx after the server stored it | before
#       retrying, the client re-reads the workflow; if a version with the same
#       note exists, it is taken as the result, so no duplicate is created
def test_a_propose_the_server_stored_before_its_5xx_is_not_sent_twice():
    from stepper.brightsky.models import Proposal

    note = "stepper heal of v1 in run idem-123: step 2 link The Hobbit -> #healed-link"
    stored = detail_json(versions=[version_view(1, note="seed"),
                                   version_view(2, note=note, source="stepper")])
    backend = (FakeBackend()
               .on("POST", versions_path(), (503, error_body(503, "upstream timeout")))
               .on("GET", detail_path(), (200, stored)))
    client = make_client(backend)

    number = client.propose_version(SLUG, Proposal(steps=pilot_steps(), source="stepper",
                                                   note=note))

    assert number == 2
    assert len(backend.sent("POST", versions_path())) == 1
    assert len(backend.sent("GET", detail_path())) == 1


def test_a_propose_the_server_did_not_store_is_retried_once():
    from stepper.brightsky.models import Proposal

    backend = (FakeBackend()
               .on("POST", versions_path(), (503, error_body(503, "busy")),
                   (201, version_view(2, note="n", source="haiku")))
               .on("GET", detail_path(), (200, detail_json())))
    client = make_client(backend)

    number = client.propose_version(SLUG, Proposal(steps=pilot_steps(), source="haiku",
                                                   note="run idem-9"))

    assert number == 2
    assert backend.calls() == [
        ("POST", versions_path()), ("GET", detail_path()), ("POST", versions_path()),
    ]


# Interfaces: `RunReport(version, steps, result, idempotency_key, client="stepper")`
#             with `to_json()`; `RunStep(step_number, matched, tier, outcome)`
def test_report_run_posts_the_run_report_wire_shape():
    from stepper.brightsky.models import RunReport, RunStep

    backend = FakeBackend().on("POST", f"/api/workflows/{SLUG}/runs", (201, {"id": "r"}))
    client = make_client(backend)
    report = RunReport(
        version=1,
        steps=[RunStep(step_number=1, matched=True, tier="role", outcome="passed"),
               RunStep(step_number=2, matched=False, tier=None, outcome="failed")],
        result="failed",
        idempotency_key="idem-1",
    )

    client.report_run(SLUG, report)

    sent = backend.sent("POST", f"/api/workflows/{SLUG}/runs")
    assert len(sent) == 1
    body = sent[0].body
    assert body["version"] == 1
    assert body["result"] == "failed"
    assert body["client"] == "stepper"
    assert body["idempotencyKey"] == "idem-1"
    assert [(s["stepNumber"], s["matched"], s["outcome"]) for s in body["steps"]] == [
        (1, True, "passed"), (2, False, "failed"),
    ]
    assert body["steps"][0]["tier"] == "role"
    assert body["steps"][1].get("tier") is None
