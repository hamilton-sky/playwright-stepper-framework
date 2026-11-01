# Add the BrightSky HTTP client with its retry policy

Type: task
Status: resolved
Blocked by: 02
Test first: yes
Level: 3
Touches: stepper/brightsky/client.py, stepper/tests/unit/test_brightsky_client.py

`stepper/brightsky/client.py` (new) is the other half of the trust boundary to the
backend: the bridge token goes out on every request, and every body that comes back is
read with ticket 02's validating readers. Level 3.

- **Transport.** A `Transport` Protocol, `send(method, url, headers, body: bytes | None,
  timeout: float) -> HttpResponse`, an `HttpResponse(status: int, body: bytes)`
  dataclass, and `UrllibTransport`. An HTTP error status is returned as an
  `HttpResponse`, not raised. A network failure raises `OSError`. Loopback hosts use
  `urllib.request.build_opener(ProxyHandler({}))`; other hosts use the default opener.
  See map.md for the docs line on why.
- **`BrightSkyClient(config, transport=None, sleep=time.sleep)`** has `queue()`,
  `get_workflow(slug)`, `report_run(slug, report)` and `propose_version(slug,
  proposal)`.
  - `queue()` returns `(items, rejected)`, the items in the backend's order. A body that
    is not a JSON array raises `BrightSkyResponseError`. A single malformed entry is left
    out, and its reason (`entry 3: slug '../x' is not a valid slug`) goes into
    `rejected`, so one bad row cannot stop the rest.
  - Paths: `GET /api/workflows/verification-queue`; `GET /api/workflows/<slug>`, where
    the slug is checked against ticket 02's `SLUG_PATTERN` before any request and
    URL-quoted; `POST /api/workflows/<slug>/runs`; `POST /api/workflows/<slug>/versions`.
  - Every request sends `Authorization: Bearer <token>`, `Accept: application/json`,
    JSON bodies, and a timeout of 20 s.
- **Retry policy, in one helper.**
  - A status ≥ 500, or an `OSError` (which covers `URLError` and `TimeoutError`), is
    retried exactly once after `sleep(1.0 + random.uniform(0, 0.5))`.
  - A 4xx is never retried.
  - A final failure raises `BrightSkyHttpError(status, message)`, with the status 0 for
    a network error and the message taken from the backend's JSON `message` field when
    there is one. Neither the status line nor the message ever holds the token.
- `report_run` resends the same body, idempotency key included, on its retry; the
  backend dedupes by key.
- `propose_version` checks before it retries: it calls `get_workflow` and, if a version
  in the detail's `versions` has a `note` equal to the proposal's note, returns that
  version number instead of posting again.
- One log line per request through `logging.getLogger(__name__)`, with method, path,
  status, attempt and duration_ms. Never the token, never a body.

Tests use a stubbed `Transport` that records calls and replays scripted responses, and a
`sleep` that records delays. One test drives `UrllibTransport` against an `http.server`
on `127.0.0.1` in a thread, with the proxy environment variables set to a dead proxy, to
prove loopback skips the proxy.

## Not in this ticket

- The config and the wire models; ticket 02.
- Exit codes and stderr output; ticket 07.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q` passes. Its retry
  tests show that a 503 then a 200 makes exactly two calls with one recorded sleep, that
  two 503s raise `BrightSkyHttpError(503, ...)` after two calls, that a 400, 401, 404 or
  429 raises after exactly one call with no sleep, and that a network `OSError` is
  retried once.
- In the same file, a retried `report_run` sends a byte-identical body, and a propose
  whose first POST got a 503 but whose re-read finds the same note returns that version
  with exactly one versions POST.
- In the same file, every recorded request carries `Authorization: Bearer <token>`, a
  slug `../x` raises before any call, a queue body that is not an array raises
  `BrightSkyResponseError`, and a queue with one valid entry and one with slug `../x`
  returns one item and one rejected reason; the token appears in no log record
  (`caplog`).
- The `UrllibTransport` loopback test in the same file passes with `HTTP_PROXY`,
  `HTTPS_PROXY` and `ALL_PROXY` set to an unreachable proxy.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Interfaces, § Edge cases, § Decisions ("HTTP client", "Token transport",
  "Proposal retry safety")
- map.md § Decisions so far (urllib ProxyHandler source, bright-sky route facts)
- `stepper/sites/saucedemo/fixtures/server.py` for an existing stdlib `http.server`
  pattern

## Answer

- **Built**: `stepper/brightsky/client.py` (new: `TIMEOUT`, `HttpResponse`, `Transport`,
  `UrllibTransport`, `BrightSkyHttpError`, `BrightSkyClient`; re-exports
  `BrightSkyResponseError`), `stepper/tests/unit/test_brightsky_client.py` (new).
  Test-only commit 960a04f first; it failed at collection with
  `ModuleNotFoundError: No module named 'stepper.brightsky.client'`.
- **Proof** (all run after the last edit):
  - `python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q` → `49 passed`.
    Retry: 503 then 200 → 2 calls, 1 sleep in [1.0, 1.5]; two 503s →
    `BrightSkyHttpError` status 503, message "still busy", 2 calls; 400/401/404/429 → 1
    call, `sleeps == []`; `ConnectionRefusedError`, `TimeoutError`, `OSError` each retried
    once (2 calls, 1 sleep); two network errors → status 0.
  - Same file: a 502-then-201 `report_run` sends `first.body == second.body` with
    `idempotencyKey` intact; a propose whose POST got 503 and whose re-read finds the
    note returns 2 with calls `[POST versions, GET detail]` (one POST); not found → a
    second, byte-identical POST, returns 3.
  - Same file: every request (queue, detail, runs ×2, versions) has
    `Authorization: Bearer <token>`, `Accept: application/json`, timeout 20; slugs
    `../x`, `a/b/c`, `Find-Author`, `ab`, `abc\n`, `abc?x=1` raise `ValueError` with
    `stub.sent == []` for get/report/propose; queue bodies `{"items": []}`, `"[]"`,
    `null`, non-JSON, bad UTF-8 raise `BrightSkyResponseError`; a queue of one valid
    entry and `../x` gives 1 item and `entry 2: slug must match ...`; the caplog test sees
    exactly 3 records for 3 sends, each with method/path/status/attempt/duration_ms, no
    token (even when the OSError text and the backend message contain it), no body.
  - Loopback: `test_urllib_transport_skips_the_proxy_for_loopback` passes with
    `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (and lowercase) at `http://127.0.0.1:9` and
    `NO_PROXY`/`no_proxy` removed; the control test shows a plain
    `urllib.request.build_opener()` raises `URLError` under the same env, and a 404 comes
    back as `HttpResponse(404)`.
  - `python3 -m pytest stepper/tests/unit/ -q` → `1933 passed`.
  - Also: Build exit 0, Lint exit 0, and
    `plans/brightsky-verify/acceptance/test_accept_config_client.py` → `34 passed` (was
    21 failed).
- **Decisions**:
  - A bad slug raises `ValueError` (a caller bug, as the models' writers do); ticket 07
    validates the CLI slug itself and exits 3 before the client is called.
  - Queue rejection reasons are `entry <n>: <reader message>`, n counted from 1. The
    reader's message names the rule, not the value (ticket 02's choice), so the reason
    reads `entry 2: slug must match ^[a-z0-9-]{3,100}\Z`, not the ticket's example with
    the value quoted.
  - `UrllibTransport` follows no redirects (both openers): urllib forwards
    `Authorization` on a redirect to any host or scheme, which would leak the token. A
    3xx comes back as a non-retried `BrightSkyHttpError`. `http.client.HTTPException`
    (cut-off or malformed response) is raised as `OSError`, per the Transport contract.
  - Propose retry: sleep, then `get_workflow` (with its own retry), then a note match
    returns that version; else one more POST. If the re-read itself fails, its error
    propagates and nothing is re-posted (no duplicate on uncertainty).
  - A backend message that is a list of strings (NestJS validation) is joined with
    "; "; no usable message falls back to the status phrase; messages are cut to 500
    characters and any occurrence of the token is replaced with `<token>`.
  - `str(BrightSkyHttpError)` is `HTTP <status>: <message>`, or just the message for
    status 0 (`network error: <Type>: <text>`). Log level INFO for 2xx, WARNING otherwise.
- **Shortcuts taken**: the response body is read in full with no size cap; the backend is
  trusted not to send huge bodies. Worth a cap if the client ever talks to a host other
  than the store's own backend.
- **For later tickets**: 06 and 07 branch on `BrightSkyHttpError.status` (0 = network)
  and `.message`; the client raises `ValueError` for a bad slug, so 07 must validate the
  slug first (as planned). Import `BrightSkyResponseError` from either module (same class).
