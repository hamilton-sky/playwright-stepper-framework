"""
stepper.brightsky.client: the half of the trust boundary to the BrightSky
backend that does I/O.

Every request carries the bridge token and nothing else of it leaks: not into a
log record, not into an error. Every body that comes back goes through the
validating readers. A 5xx or a network error is retried exactly once after a
backoff, a 4xx never, and a propose is never posted twice when the first POST
was stored.

The client tests use a recording `Transport` that replays scripted responses
and a `sleep` that records delays. One test drives `UrllibTransport` against a
real `http.server` on 127.0.0.1 with every proxy variable set to a dead proxy.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

import stepper.brightsky.client as client_module
from stepper.brightsky.client import (
    TIMEOUT,
    BrightSkyClient,
    BrightSkyHttpError,
    BrightSkyResponseError,
    HttpResponse,
    UrllibTransport,
)
from stepper.brightsky.config import BrightSkyConfig
from stepper.brightsky.models import Proposal, RunReport, RunStep

TOKEN = "bst_unit_secret_token_9d1e4b"
URL = "https://bright-sky.example.com"
SLUG = "openlibrary-find-author"

QUEUE = "/api/workflows/verification-queue"
DETAIL = f"/api/workflows/{SLUG}"
RUNS = f"/api/workflows/{SLUG}/runs"
VERSIONS = f"/api/workflows/{SLUG}/versions"


# ── doubles ───────────────────────────────────────────────────────────────────

@dataclass
class Sent:
    method: str
    url: str
    headers: dict
    body: bytes | None
    timeout: float

    @property
    def path(self) -> str:
        return urlsplit(self.url).path


class StubTransport:
    """Records every send and replays scripted responses per (method, path), in order.

    A response is `(status, payload)` (payload JSON-encoded unless bytes) or an
    exception instance, raised as a network failure would be. The last repeats.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.sent: list[Sent] = []

    def on(self, method: str, path: str, *responses: object) -> StubTransport:
        self.routes[(method, path)] = list(responses)
        return self

    def send(self, method, url, headers, body, timeout):
        call = Sent(method, url, dict(headers), body, timeout)
        self.sent.append(call)
        script = self.routes[(method, call.path)]
        response = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(response, BaseException):
            raise response
        status, payload = response
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return HttpResponse(status=status, body=raw)

    def calls(self) -> list[tuple[str, str]]:
        return [(s.method, s.path) for s in self.sent]


def _client(transport: StubTransport, sleeps: list | None = None) -> BrightSkyClient:
    sleep = sleeps.append if sleeps is not None else (lambda seconds: None)
    return BrightSkyClient(BrightSkyConfig(api_url=URL, token=TOKEN),
                           transport=transport, sleep=sleep)


def _error(status: int, message: object) -> dict:
    return {"statusCode": status, "message": message, "error": "Error"}


def _step(title: str = "Open the book page") -> dict:
    return {"title": title, "explanation": "Click the title.",
            "target": {"role": "link", "accessibleName": "The Hobbit",
                       "selectors": [], "score": 0.8, "grounding": "current_page"}}


def _version(n: int, note: str | None = None) -> dict:
    return {"id": f"ver-{n}", "version": n, "status": "unverified",
            "source": "stepper", "note": note, "createdAt": "2026-10-30T10:00:00.000Z"}


def _detail(versions: list[dict] | None = None) -> dict:
    versions = versions if versions is not None else [_version(1)]
    return {"slug": SLUG, "site": "openlibrary.org", "currentVersion": versions[-1],
            "currentSteps": [_step()], "versions": versions}


def _queue_item(slug: str, version: int = 1) -> dict:
    return {"slug": slug, "version": version, "stepperRuns": 0,
            "createdAt": "2026-10-01T00:00:00.000Z"}


def _report() -> RunReport:
    return RunReport(version=1,
                     steps=[RunStep(step_number=1, matched=True, tier="role",
                                    outcome="passed")],
                     result="passed", idempotency_key="stepper-key-1")


# ── retry policy ──────────────────────────────────────────────────────────────

def test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep():
    sleeps: list = []
    stub = StubTransport().on("GET", DETAIL, (503, _error(503, "busy")), (200, _detail()))

    detail = _client(stub, sleeps).get_workflow(SLUG)

    assert detail.slug == SLUG
    assert stub.calls() == [("GET", DETAIL), ("GET", DETAIL)]
    assert len(sleeps) == 1
    assert 1.0 <= sleeps[0] <= 1.5


def test_two_503s_raise_brightsky_http_error_503_after_two_calls():
    sleeps: list = []
    stub = StubTransport().on("GET", DETAIL, (503, _error(503, "still busy")))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub, sleeps).get_workflow(SLUG)

    assert caught.value.status == 503
    assert caught.value.message == "still busy"
    assert len(stub.sent) == 2
    assert len(sleeps) == 1


@pytest.mark.parametrize("status", [400, 401, 404, 429])
def test_a_4xx_raises_after_exactly_one_call_with_no_sleep(status):
    sleeps: list = []
    stub = StubTransport().on("GET", DETAIL, (status, _error(status, "the backend said no")))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub, sleeps).get_workflow(SLUG)

    assert caught.value.status == status
    assert caught.value.message == "the backend said no"
    assert str(status) in str(caught.value)
    assert len(stub.sent) == 1
    assert sleeps == []


@pytest.mark.parametrize("failure", [ConnectionRefusedError("refused"),
                                     TimeoutError("timed out"), OSError("down")])
def test_a_network_oserror_is_retried_once(failure):
    sleeps: list = []
    stub = StubTransport().on("GET", QUEUE, failure, (200, [_queue_item(SLUG)]))

    items, rejected = _client(stub, sleeps).queue()

    assert [i.slug for i in items] == [SLUG]
    assert rejected == []
    assert len(stub.sent) == 2
    assert len(sleeps) == 1


def test_two_network_errors_raise_with_status_0():
    stub = StubTransport().on("GET", QUEUE, OSError("connection refused"))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).queue()

    assert caught.value.status == 0
    assert len(stub.sent) == 2


def test_a_list_message_is_joined_and_a_missing_message_falls_back():
    stub = StubTransport().on("POST", RUNS, (400, _error(400, ["version must be >= 1",
                                                               "steps too long"])))
    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).report_run(SLUG, _report())
    assert caught.value.message == "version must be >= 1; steps too long"

    stub = StubTransport().on("GET", DETAIL, (404, b"<html>nope</html>"))
    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).get_workflow(SLUG)
    assert caught.value.status == 404
    assert caught.value.message == "Not Found"


def test_a_backend_message_that_echoes_the_token_is_scrubbed():
    stub = StubTransport().on("GET", QUEUE, (401, _error(401, f"bad token {TOKEN}")))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).queue()

    assert TOKEN not in str(caught.value)
    assert TOKEN not in caught.value.message


def test_a_token_across_the_message_cut_is_scrubbed_whole():
    message = "a" * 490 + TOKEN          # the 500-character cut falls inside the token
    stub = StubTransport().on("GET", QUEUE, (400, _error(400, message)))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).queue()

    assert caught.value.message == "a" * 490 + "<token>"
    assert TOKEN[:8] not in str(caught.value)


def test_control_characters_in_a_backend_message_are_replaced():
    message = "x\n::error::pwn\u001b[31m\r\t\u0085\u2028end"
    stub = StubTransport().on("GET", QUEUE, (400, _error(400, message)))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).queue()

    assert caught.value.message.isprintable()
    assert "\n" not in str(caught.value) and "\x1b" not in str(caught.value)
    assert caught.value.message.startswith("x")
    assert caught.value.message.endswith("end")


def test_a_deeply_nested_error_body_falls_back_to_the_reason_phrase():
    stub = StubTransport().on("GET", QUEUE, (400, b"[" * 200_000))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub).queue()

    assert caught.value.status == 400
    assert caught.value.message == "Bad Request"


def test_a_retried_report_run_sends_a_byte_identical_body():
    stub = StubTransport().on("POST", RUNS, (502, _error(502, "bad gateway")),
                              (201, {"id": "run-1"}))

    _client(stub).report_run(SLUG, _report())

    assert stub.calls() == [("POST", RUNS), ("POST", RUNS)]
    first, second = stub.sent
    assert first.body is not None and first.body == second.body
    assert json.loads(first.body)["idempotencyKey"] == "stepper-key-1"


# ── propose retry safety ──────────────────────────────────────────────────────

NOTE = "Healed by stepper run stepper-key-1 of v1: step 1 target a -> b"


def _proposal() -> Proposal:
    return Proposal(steps=[_step()], source="stepper", note=NOTE)


def test_propose_returns_the_new_version_number():
    stub = StubTransport().on("POST", VERSIONS, (201, _version(2, NOTE)))

    assert _client(stub).propose_version(SLUG, _proposal()) == 2
    assert json.loads(stub.sent[0].body) == _proposal().to_json()


def test_a_propose_whose_503_was_stored_returns_that_version_with_one_post():
    stub = (StubTransport()
            .on("POST", VERSIONS, (503, _error(503, "upstream timeout")))
            .on("GET", DETAIL, (200, _detail([_version(1, "seed"), _version(2, NOTE)]))))

    number = _client(stub).propose_version(SLUG, _proposal())

    assert number == 2
    assert stub.calls() == [("POST", VERSIONS), ("GET", DETAIL)]


def test_a_propose_whose_503_was_not_stored_posts_once_more():
    stub = (StubTransport()
            .on("POST", VERSIONS, (503, _error(503, "busy")), (201, _version(3, NOTE)))
            .on("GET", DETAIL, (200, _detail([_version(1, "seed"), _version(2, "other")]))))

    number = _client(stub).propose_version(SLUG, _proposal())

    assert number == 3
    assert stub.calls() == [("POST", VERSIONS), ("GET", DETAIL), ("POST", VERSIONS)]
    assert stub.sent[0].body == stub.sent[2].body


@pytest.mark.parametrize("detail", [(500, _error(500, "db down")), (200, {"slug": SLUG})],
                         ids=["re-read-5xx", "re-read-malformed"])
def test_a_propose_whose_re_read_fails_raises_the_post_error_and_does_not_re_post(detail):
    sleeps: list = []
    stub = (StubTransport()
            .on("POST", VERSIONS, (503, _error(503, "upstream timeout")))
            .on("GET", DETAIL, detail))

    with pytest.raises(BrightSkyHttpError) as caught:
        _client(stub, sleeps).propose_version(SLUG, _proposal())

    assert caught.value.status == 503
    assert caught.value.message == "upstream timeout"
    assert isinstance(caught.value.__cause__, (BrightSkyHttpError, BrightSkyResponseError))
    assert stub.calls().count(("POST", VERSIONS)) == 1
    assert stub.calls()[0] == ("POST", VERSIONS)


def test_a_propose_4xx_is_not_retried_and_does_not_re_read():
    stub = StubTransport().on("POST", VERSIONS, (400, _error(400, "bad steps")))

    with pytest.raises(BrightSkyHttpError):
        _client(stub).propose_version(SLUG, _proposal())

    assert stub.calls() == [("POST", VERSIONS)]


def test_a_propose_response_without_a_version_raises_a_response_error():
    stub = StubTransport().on("POST", VERSIONS, (201, {"id": "ver-2"}))

    with pytest.raises(BrightSkyResponseError, match="version"):
        _client(stub).propose_version(SLUG, _proposal())


# ── requests ──────────────────────────────────────────────────────────────────

def test_every_request_carries_the_bearer_token_json_headers_and_the_timeout():
    stub = (StubTransport()
            .on("GET", QUEUE, (200, []))
            .on("GET", DETAIL, (200, _detail()))
            .on("POST", RUNS, (503, _error(503, "busy")), (201, {"id": "r"}))
            .on("POST", VERSIONS, (201, _version(2, NOTE))))
    client = _client(stub)

    client.queue()
    client.get_workflow(SLUG)
    client.report_run(SLUG, _report())
    client.propose_version(SLUG, _proposal())

    assert stub.calls() == [("GET", QUEUE), ("GET", DETAIL), ("POST", RUNS),
                            ("POST", RUNS), ("POST", VERSIONS)]
    for sent in stub.sent:
        assert sent.headers["Authorization"] == f"Bearer {TOKEN}"
        assert sent.headers["Accept"] == "application/json"
        assert sent.timeout == TIMEOUT == 20
        assert sent.url == URL + sent.path
        if sent.method == "POST":
            assert sent.headers["Content-Type"] == "application/json"
            json.loads(sent.body)
        else:
            assert sent.body is None


@pytest.mark.parametrize("call", ["get_workflow", "report_run", "propose_version"])
@pytest.mark.parametrize("slug", ["../x", "a/b/c", "Find-Author", "ab", "abc\n", "abc?x=1"])
def test_a_bad_slug_raises_before_any_call(call, slug):
    stub = StubTransport()
    client = _client(stub)
    args = {"get_workflow": (), "report_run": (_report(),),
            "propose_version": (_proposal(),)}[call]

    with pytest.raises(ValueError, match="slug"):
        getattr(client, call)(slug, *args)

    assert stub.sent == []


# ── reading bodies ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [{"items": []}, "[]", None, b"not json", b"\xff\xfe"])
def test_a_queue_body_that_is_not_a_json_array_raises_a_response_error(body):
    stub = StubTransport().on("GET", QUEUE, (200, body))

    with pytest.raises(BrightSkyResponseError):
        _client(stub).queue()


@pytest.mark.parametrize("call", ["queue", "get_workflow"])
def test_a_deeply_nested_body_raises_a_response_error(call):
    stub = (StubTransport().on("GET", QUEUE, (200, b"[" * 200_000))
            .on("GET", DETAIL, (200, b'{"a":' * 200_000)))

    with pytest.raises(BrightSkyResponseError):
        getattr(_client(stub), call)(*([] if call == "queue" else [SLUG]))


def test_a_queue_with_one_bad_slug_returns_one_item_and_one_reason():
    stub = StubTransport().on("GET", QUEUE, (200, [_queue_item(SLUG, 2),
                                                   _queue_item("../x")]))

    items, rejected = _client(stub).queue()

    assert [(i.slug, i.version) for i in items] == [(SLUG, 2)]
    assert len(rejected) == 1
    assert rejected[0].startswith("entry 2: ")
    assert "slug" in rejected[0]


def test_a_malformed_detail_raises_a_response_error_naming_the_field():
    body = _detail()
    del body["currentVersion"]
    stub = StubTransport().on("GET", DETAIL, (200, body))

    with pytest.raises(BrightSkyResponseError, match="currentVersion"):
        _client(stub).get_workflow(SLUG)


# ── logging ───────────────────────────────────────────────────────────────────

def test_one_log_line_per_request_and_never_the_token_or_a_body(caplog):
    caplog.set_level(logging.DEBUG, logger="stepper.brightsky.client")
    stub = (StubTransport()
            .on("GET", QUEUE, OSError(f"refused {TOKEN}"), (200, [_queue_item("../x")]))
            .on("POST", RUNS, (401, _error(401, f"token {TOKEN} revoked"))))
    client = _client(stub)

    client.queue()
    with pytest.raises(BrightSkyHttpError) as caught:
        client.report_run(SLUG, _report())

    records = [r for r in caplog.records if r.name == "stepper.brightsky.client"]
    assert len(records) == len(stub.sent) == 3
    for record in records:
        text = record.getMessage()
        assert TOKEN not in text
        assert "stepper-key-1" not in text          # no body
        for word in ("method", "path", "status", "attempt", "duration_ms"):
            assert word in text
    assert "attempt=2" in records[1].getMessage()
    assert TOKEN not in str(caught.value)
    assert TOKEN not in caplog.text


# ── UrllibTransport against a real loopback server ────────────────────────────

class _Backend(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        _Backend.seen.append({"method": self.command, "path": self.path,
                              "auth": self.headers.get("Authorization"), "body": body})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://198.51.100.1/steal")
            self.end_headers()
            return
        if self.path.startswith("/sized"):
            # /sized?n=<bytes>&status=<code>: a body of exactly n bytes.
            query = dict(part.split("=") for part in urlsplit(self.path).query.split("&"))
            payload = b"x" * int(query["n"])
            self.send_response(int(query.get("status", "200")))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        status = 404 if self.path == "/missing" else 200
        payload = json.dumps({"ok": status == 200, "echo": body.decode()}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _answer
    do_POST = _answer

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def loopback_server() -> Iterator[str]:
    _Backend.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def dead_proxy(monkeypatch) -> str:
    """Every proxy variable points at a port nothing listens on; no bypass list."""
    proxy = "http://127.0.0.1:9"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, proxy)
        monkeypatch.setenv(name.lower(), proxy)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    return proxy


def test_urllib_transport_skips_the_proxy_for_loopback(loopback_server, dead_proxy):
    transport = UrllibTransport()

    ok = transport.send("POST", loopback_server + "/api/x",
                        {"Authorization": f"Bearer {TOKEN}",
                         "Content-Type": "application/json"},
                        b'{"a": 1}', 5.0)
    missing = transport.send("GET", loopback_server + "/missing", {}, None, 5.0)

    assert ok.status == 200
    assert json.loads(ok.body) == {"ok": True, "echo": '{"a": 1}'}
    assert missing.status == 404          # an HTTP error status is returned, not raised
    assert _Backend.seen[0]["auth"] == f"Bearer {TOKEN}"
    assert [s["path"] for s in _Backend.seen] == ["/api/x", "/missing"]


def test_the_default_opener_would_have_used_the_dead_proxy(loopback_server, dead_proxy):
    """Control: with these variables, a plain urllib opener fails, so the test above
    passes only because the loopback opener ignores the environment's proxies."""
    import urllib.error
    import urllib.request

    with pytest.raises(urllib.error.URLError):
        urllib.request.build_opener().open(loopback_server + "/api/x", timeout=5)
    assert _Backend.seen == []


def test_urllib_transport_does_not_follow_a_redirect(loopback_server, dead_proxy):
    response = UrllibTransport().send("GET", loopback_server + "/redirect",
                                      {"Authorization": f"Bearer {TOKEN}"}, None, 5.0)

    assert response.status == 302
    assert [s["path"] for s in _Backend.seen] == ["/redirect"]


def test_urllib_transport_raises_oserror_on_a_network_failure(dead_proxy):
    with pytest.raises(OSError):
        UrllibTransport().send("GET", "http://127.0.0.1:9/api/x", {}, None, 5.0)


@pytest.mark.parametrize("status", [200, 500])
def test_urllib_transport_refuses_a_body_over_the_cap(loopback_server, dead_proxy,
                                                      monkeypatch, status):
    monkeypatch.setattr(client_module, "MAX_BODY", 64)
    transport = UrllibTransport()

    exact = transport.send("GET", f"{loopback_server}/sized?n=64&status={status}",
                           {}, None, 5.0)
    assert (exact.status, len(exact.body)) == (status, 64)

    with pytest.raises(OSError, match="64"):
        transport.send("GET", f"{loopback_server}/sized?n=65&status={status}", {}, None, 5.0)
