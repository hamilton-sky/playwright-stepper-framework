# Add the BrightSky HTTP client with its retry policy

Type: task
Status: open
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
