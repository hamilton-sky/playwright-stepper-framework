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
- **Review fixes** (round 1; failing tests first in b486975, 5 failed for the right
  reasons, then the fix):
  1. Token across the cut: `_message` now scrubs, then cuts
     (`self._scrub(message)[:MAX_MESSAGE]`). New test
     `test_a_token_across_the_message_cut_is_scrubbed_whole` (490 'a' + token) gives
     `"a" * 490 + "<token>"`; before the fix it ended in `bst_unit_s`.
  2. Body cap: `UrllibTransport` reads at most `MAX_BODY` (4 MiB) + 1 bytes through
     `_read_capped`, for 2xx and error bodies alike; a larger body raises `OSError`
     (a failed response, per the Transport contract), so the policy retries it once and
     then raises `BrightSkyHttpError(0, ...)`. This also supersedes the earlier
     "Shortcuts taken" line about no size cap. New test
     `test_urllib_transport_refuses_a_body_over_the_cap[200|500]` (cap patched to 64:
     64 bytes pass, 65 raise).
  3. Propose re-read failure: in `_request`, a `BrightSkyHttpError` or
     `BrightSkyResponseError` from `before_retry` is logged (type only) and the first
     attempt's error is raised with the re-read's chained (`raise failure from err`);
     nothing is re-posted, keeping "no duplicate on uncertainty". New test
     `test_a_propose_whose_re_read_fails_raises_the_post_error_and_does_not_re_post`
     [re-read-5xx | re-read-malformed]: status 503 "upstream timeout", `__cause__` set,
     one versions POST.
  Proof after the fixes: client file `54 passed`; `stepper/tests/unit/` `1938 passed`;
  Build exit 0; Lint exit 0; `test_accept_config_client.py` `34 passed`.
- **Review fixes** (round 2; failing tests first in 823eb2d, 4 failed for the right
  reasons: `RecursionError` from `json.loads` x3 and the message keeping `\n`/`\x1b`;
  then the fix):
  1. Deep nesting: `_json` and `_message` also catch `RecursionError`. `_json` raises
     `BrightSkyResponseError`, `_message` falls back to the reason phrase. New tests
     `test_a_deeply_nested_body_raises_a_response_error[queue|get_workflow]` (200 with
     `b"[" * 200000` / `b'{"a":' * 200000`) and
     `test_a_deeply_nested_error_body_falls_back_to_the_reason_phrase` (400 with
     `b"[" * 200000` gives `BrightSkyHttpError(400, "Bad Request")`).
  2. Control characters: `_message` replaces every non-printable character
     (`str.isprintable`, so also `\x85` and `\u2028`) with a space after scrubbing and
     before the cut. New test `test_control_characters_in_a_backend_message_are_replaced`.
  3. Timeout: took the reviewer's second option and recorded on `TIMEOUT` that it is
     urllib's per socket operation timeout, not a total deadline. A total deadline would
     need a watchdog thread or a hand-rolled socket loop in `UrllibTransport`; the CI
     job timeout bounds it today. This is a shortcut: worth a deadline if the client ever
     runs where no outer job timeout exists.
  Proof after the fixes: client file `58 passed`; `stepper/tests/unit/` `1942 passed`;
  Build exit 0; Lint exit 0; `test_accept_config_client.py` `34 passed`.

## Review findings (round 1, pair review)

QUALITY
1. major /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`_message`): the message is cut to 500 characters before the token is scrubbed (`return self._scrub(message[:MAX_MESSAGE])`). If a backend message holds the token across the 500-character cut, the cut leaves only a prefix of the token, and `_scrub` cannot match a prefix, so that part of the token stays in the message. I reproduced it: a 400 whose `message` was 490 'a' characters followed by the token produced a `BrightSkyHttpError.message` ending in `aaaaaaaaaaSECRETTOKE`. That breaks the ticket's rule that the message never holds the token, and this error goes to stderr and CI logs. Fix: scrub first, then cut (`self._scrub(message)[:MAX_MESSAGE]`), and add a test that puts the token across the cut.
2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`UrllibTransport.send`): `response.read()` and `err.read()` read the whole body with no size limit, so a hostile or broken backend can make the client use unbounded memory. Fix: read at most a fixed cap (for example a few MB) and treat a larger body as a bad response.
3. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`propose_version`): before its retry, propose re-reads the workflow through `get_workflow`. If that re-read fails, its error comes out of `propose_version` in place of the error from the versions POST, so the caller sees a GET failure for a POST call. Fix: catch the re-read's error, log it, and go on with the POST retry, or raise the POST's error with the re-read's error chained to it.

Inputs I probed as a hostile caller:
- Slugs (`../x`, a non-string): `_workflow_path` checks them against `SLUG_PATTERN` before any request, so no way through.
- Token in headers: `load_config` refuses a token that is not visible ASCII, which blocks header injection.
- Token in error and log text: a scrubbed `OSError` text and exact-match messages are clean. The only way through is the cut in finding 1.
- The exception chain: a network `failure` is raised after the loop, so nothing is chained to it.
- Redirects: `_NoRedirect` hands a 3xx back as a response, so the Authorization header is not forwarded.
- Proxies: loopback skips them; the test deletes both `NO_PROXY` spellings and sets both cases of the proxy variables, so it would catch a regression.
- Queue entry errors from models.py: they do not echo the values the backend sent.
- Matching a proposal by its note: each note carries a fresh key, so matching an older version by note is not a practical risk.
- 4xx responses: no retry and no re-read.

Done when: `python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q` gave 49 passed, and `python3 -m pytest stepper/tests/unit/ -q` gave 1933 passed.

Range and process: I reviewed a5af20e..13d014b. That last commit is both the ticket's newest commit and HEAD, so I left no later commits out. I read the ticket as it stood at a5af20e, so I did not see its Answer, and I read the ticket's hunk only for its Status line (open to resolved). My commands left no files behind. The read-only hook blocked one Bash call because it included a `mkdir`; that call did not run, and I re-ran the same commands without it.

REVIEW: FAIL

Review of `brightsky-verify 10 a5af20e85db090ed51c074acc7e38820553d80c3` (spec pass). Ticket: /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/tasks/10-brightsky-client.md. I read it as it stood at a5af20e, with the Answer still empty. The ticket's last commit is END = 13d014b, which is also HEAD, so no later commits were left out. I did not read the Answer. The ticket's Status line went from open to resolved.

SPEC
- test_brightsky_client.py passes, with retry tests for 503 then 200 (two calls, one sleep), two 503s (`BrightSkyHttpError(503, ...)` after two calls), 400/401/404/429 (one call, no sleep) and a network `OSError` retried once: MET (conductor). I also read the file and found each case: `test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep`, `test_two_503s_raise_brightsky_http_error_503_after_two_calls`, `test_a_4xx_raises_after_exactly_one_call_with_no_sleep[400|401|404|429]` and `test_a_network_oserror_is_retried_once`.
- A retried `report_run` sends a byte-identical body, and a propose that got a 503 but finds the same note on the re-read returns that version after one versions POST: MET (conductor). The tests are `test_a_retried_report_run_sends_a_byte_identical_body` and `test_a_propose_whose_503_was_stored_returns_that_version_with_one_post`. The second asserts the calls were exactly POST versions, then GET detail.
- Every request carries `Bearer <token>`, slug `../x` raises before any call, a queue body that is not an array raises `BrightSkyResponseError`, a queue with one good and one `../x` entry gives one item and one reason, and the token is in no caplog record: MET (conductor). The tests are `test_every_request_carries_the_bearer_token_json_headers_and_the_timeout`, `test_a_bad_slug_raises_before_any_call` (it includes `../x`), `test_a_queue_body_that_is_not_a_json_array_raises_a_response_error`, `test_a_queue_with_one_bad_slug_returns_one_item_and_one_reason`, and `test_one_log_line_per_request_and_never_the_token_or_a_body`, which checks `caplog`.
- The `UrllibTransport` loopback test passes with `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` set to an unreachable proxy: MET (conductor). The `dead_proxy` fixture sets all three, in upper and lower case, to http://127.0.0.1:9 and removes `NO_PROXY`/`no_proxy`. A control test shows a plain opener fails under the same environment.
- All existing tests still pass (`python3 -m pytest stepper/tests/unit/ -q`): MET (conductor).
- Acceptance: I ran `python3 -m pytest plans/brightsky-verify/acceptance/test_accept_config_client.py -q` myself, since it covers what this ticket delivers. It printed "34 passed". The acceptance failures the conductor reported are all in test_accept_verify_cli.py, which is ticket 07's CLI. Ticket 07 has not been built (it is not in the log), so those failures do not count against this ticket.
- scope: OK. Over a5af20e..13d014b the changed files are stepper/brightsky/client.py and stepper/tests/unit/test_brightsky_client.py, which the ticket's Touches line names. The others are bookkeeping that every ticket commit is expected to touch: the ticket file, one appended line in plans/brightsky-verify/map.md, and one appended line tagged (10) in plans/brightsky-verify/learnings.md. There are no unrelated edits, and nothing from ticket 02 (config, models) or ticket 07 (exit codes, stderr) was changed.
- test first: OK. Commit 960a04f adds only stepper/tests/unit/test_brightsky_client.py. That test imports `stepper.brightsky.client`, which did not exist before 13d014b, so it fails without the production change. The conductor saw 960a04f fail before the code landed.

The ticket is already level 3, so no level raise is needed. My pytest run may have refreshed `__pycache__` files under plans/brightsky-verify/acceptance/; I left them as they were.

REVIEW: PASS

## Review findings (round 2, pair review)

Quality pass for ticket 10 of brightsky-verify (`brightsky-verify 10 a5af20e85db090ed51c074acc7e38820553d80c3`). The review fails on one major finding: a hostile backend can make the client raise `RecursionError`, which is not one of its documented errors.

**Scope**
- Range: a5af20e..3778ff9. The ticket's newest commit (3778ff9) is also HEAD, so no later commits were left out.
- I read the ticket as it stood at a5af20e, with the Answer still empty.
- I read the round-1 review findings, which sit after the Answer, from their own heading onward. I did not read the Answer itself.
- The ticket's Status line goes from open to resolved.
- Round 1's three findings are fixed in 3778ff9:
  - The message is now scrubbed before it is cut to 500 characters.
  - Response bodies are capped at 4 MB.
  - A failed re-read now raises the error from the versions POST, with the re-read's error chained to it.

**Commands run**
- `python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q`: 54 passed.
- `python3 -m pytest stepper/tests/unit/ -q`: 1938 passed.
- `plans/brightsky-verify/acceptance/test_accept_config_client.py`: 34 passed.
- The acceptance failures the conductor saw are all in `test_accept_verify_cli.py`, which tests ticket 07's CLI. That ticket is not built yet.
- I used `-p no:cacheprovider` and `-B`, and `git status` was clean afterwards.

**Inputs probed as a hostile caller**
- Slug: checked against `SLUG_PATTERN` and quoted before any request. No way through.
- Token in headers: `load_config` only accepts visible ASCII. No way through.
- Token in errors and logs: scrubbed before the cut; log lines carry only the error type name. No way through.
- Redirects: `_NoRedirect` returns a 3xx as an error response, so the Authorization header is not forwarded.
- Proxies on loopback: skipped, and the test covers both spellings of each variable.
- Response size: capped at 4 MB.
- Propose re-read failure: raises without posting again.
- Proposal note: always a string, so matching an older version on a null note cannot happen.
- Response body nesting depth: this is the way through (finding 1).
- Error message content: control characters pass through (finding 2).
- Slow responses: the timeout is per read, not per request (finding 3).

QUALITY
1. major /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`_json`, `_message`): a deeply nested JSON body well under `MAX_BODY` makes `json.loads` raise `RecursionError`, and neither function catches it. I reproduced it: a 200 queue body of `b"[" * 200000` made `queue()` raise `RecursionError`, not `BrightSkyResponseError`. A 400 with the same body also raised `RecursionError`, not `BrightSkyHttpError(400, ...)`. That breaks the ticket's error contract at the trust boundary, and a CLI that catches only the documented types (ticket 07) will crash with a traceback. Change: catch `RecursionError` in `_json` and raise `BrightSkyResponseError`; in `_message`, fall back to the reason phrase. Add a test for each.
2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`_message`): the backend's message is passed through with newlines, ESC and other control characters. A body of `{"message":"x\n::error::pwn\u001b[31m"}` produced `HTTP 400: x\n::error::pwn\x1b[31m`. Once that is printed to stderr in CI, it can inject GitHub Actions workflow-command lines and terminal escape codes. Change: replace control characters (or anything that is not printable) in the message before the cut.
3. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`UrllibTransport.send`): the 20 s timeout applies to each socket read, not to the whole request, so a backend that sends a byte every few seconds can hold a request open well past 20 s. Only the 30-minute CI job timeout stops it. Change: either enforce a total deadline, or record that `TIMEOUT` is per read.

REVIEW: FAIL

Review of `brightsky-verify 10 a5af20e85db090ed51c074acc7e38820553d80c3` (spec pass, round 2). Ticket: /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/tasks/10-brightsky-client.md. I read it as it stood at a5af20e, so its Answer was still empty. I read the round 1 Review findings from the f869664 hunk, stopping before `## Answer`. I did not read the Answer.

END is 3778ff9, which is also HEAD, so no later commits were left out of the review. The ticket's Status line went from open to resolved. Round 1 had three quality findings: the token was cut before it was scrubbed, response bodies had no size cap, and an error on the propose re-read hid the POST's error. b486975 adds tests for all three and 3778ff9 fixes all three in /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py: `_message` now scrubs before it cuts, `_read_capped` caps bodies at MAX_BODY (4 MiB), and a failed re-read now raises the POST's error with the re-read's error chained to it.

SPEC
- test_brightsky_client.py passes, with retry tests for 503 then 200 (two calls, one sleep), two 503s (BrightSkyHttpError 503 after two calls), 400/401/404/429 (one call, no sleep) and a network OSError retried once: MET (conductor). I read the tests and found matching assertions in each of `test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep`, `test_two_503s_raise_brightsky_http_error_503_after_two_calls`, `test_a_4xx_raises_after_exactly_one_call_with_no_sleep[400,401,404,429]` and `test_a_network_oserror_is_retried_once`.
- A retried report_run sends a byte-identical body, and a propose whose 503 was stored returns that version after one versions POST: MET (conductor). The tests are `test_a_retried_report_run_sends_a_byte_identical_body` and `test_a_propose_whose_503_was_stored_returns_that_version_with_one_post`; the second asserts the calls were exactly [POST versions, GET detail].
- Every request carries the Bearer token, slug `../x` raises before any call, a queue body that is not an array raises BrightSkyResponseError, one good entry plus one `../x` entry gives one item and one reason, and the token is in no caplog record: MET (conductor). The tests are `test_every_request_carries_the_bearer_token_json_headers_and_the_timeout`, `test_a_bad_slug_raises_before_any_call` (which includes `../x`), `test_a_queue_body_that_is_not_a_json_array_raises_a_response_error`, `test_a_queue_with_one_bad_slug_returns_one_item_and_one_reason` and `test_one_log_line_per_request_and_never_the_token_or_a_body`.
- The UrllibTransport loopback test passes with HTTP_PROXY, HTTPS_PROXY and ALL_PROXY set to an unreachable proxy: MET (conductor). The `dead_proxy` fixture sets all three, in upper and lower case, to http://127.0.0.1:9 and removes NO_PROXY and no_proxy.
- All existing tests still pass (`python3 -m pytest stepper/tests/unit/ -q`): MET (conductor).
- Acceptance: I ran `python3 -m pytest plans/brightsky-verify/acceptance/test_accept_config_client.py -q -p no:cacheprovider` myself, since it covers this ticket. It printed "34 passed". Every failure the conductor reported is in test_accept_verify_cli.py, which belongs to ticket 07, and ticket 07 is not built yet, so those failures do not count against this ticket.
- scope: OK. Over a5af20e..3778ff9 the code changes are stepper/brightsky/client.py and stepper/tests/unit/test_brightsky_client.py, both named in Touches. The other changes are bookkeeping: the ticket file, one appended line in plans/brightsky-verify/map.md, and one appended line tagged (10) in plans/brightsky-verify/learnings.md. Nothing from ticket 02 (config, models) or ticket 07 (exit codes, stderr) was changed.
- test first: OK. 960a04f adds only the test file, and that test imports `stepper.brightsky.client`, which did not exist yet, so it fails without the production change; the conductor saw 960a04f fail. In round 2, b486975 adds tests for the three fixes before the fix commit. Two of them fail against the old code: the token-across-the-cut test fails on the old cut-then-scrub, and the body-cap test fails on the old unbounded read. I did not check whether the re-read test also fails against the old code.

The ticket is already level 3, so no level raise is needed. git status was clean, and pytest left no files behind beyond `__pycache__` folders that were already there.

REVIEW: PASS

## Review findings (round 3, pair review)

Quality pass, round 3, for `brightsky-verify 10 a5af20e85db090ed51c074acc7e38820553d80c3`. The review fails on one major finding: a backend that answers with an error status and a broken chunked body makes the client raise `http.client.IncompleteRead`. That is not one of the client's documented errors, and the 5xx is not retried.

Range: a5af20e..f86efdc. f86efdc is the ticket's newest commit and also HEAD, so I left no later commits out. I read the ticket as it stood at a5af20e. I read the round 1 and round 2 review findings from their own headings onward. I did not read the Answer. The ticket's Status line goes from open to resolved.

Round 2 findings, all fixed in f86efdc:
- `RecursionError` is now caught in `_json` (raises `BrightSkyResponseError`) and in `_message` (falls back to the reason phrase), with tests.
- Control characters in the backend's message are replaced, with a test.
- `TIMEOUT` is now documented as a per-read limit.

Done when, re-run by me:
- `python3 -m pytest stepper/tests/unit/test_brightsky_client.py -q`: 58 passed.
- `python3 -m pytest stepper/tests/unit/ -q`: 1942 passed.
- I ran both with `-p no:cacheprovider`, and `git status` was clean afterwards.

Inputs I probed as a hostile caller:
- Slug: checked against `SLUG_PATTERN` and quoted before any request. No way through.
- Token in headers, errors and logs: scrubbed before the cut, and log lines carry only the error type name. No way through.
- Error message content: control characters are replaced. No way through.
- Body nesting depth: now caught. No way through.
- Body size: capped at 4 MB. No way through.
- Redirects: a 3xx comes back as a response, so the Authorization header is not forwarded.
- Proxies on loopback: skipped.
- Propose re-read failure: raises the POST's error and does not post again.
- Malformed response framing on an error status: this is the way through (finding 1).

I ran the probes as inline stdin scripts against a raw socket server on 127.0.0.1. They wrote no files. The read-only hook blocked one call that included a `mkdir`; that call did not run.

QUALITY
1. major /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`UrllibTransport.send`): `_read_capped(err)` runs inside the `except urllib.error.HTTPError` handler. An exception raised inside one `except` clause is not caught by the next `except` clause of the same `try`, so the `except http.client.HTTPException` beside it never sees it. I reproduced it: a response of `HTTP/1.1 503 X`, `Transfer-Encoding: chunked`, then a bad chunk size (`zz`) made `BrightSkyClient.queue()` raise `http.client.IncompleteRead` on the first attempt. There was no retry, and the error was not a `BrightSkyHttpError`. A 400 with the same broken body behaves the same way. A 200 with the same body is converted to `OSError` correctly. This breaks the `Transport` contract (a network failure raises `OSError`) and the client's error contract at the trust boundary, and a CLI that catches only the documented types (ticket 07) would crash with a traceback. Fix: wrap the error-body read too, for example `try: body = _read_capped(err) except http.client.HTTPException as e: raise OSError(...) from e`, or move the `HTTPException` conversion to an outer `try`. Add a stub-server test for an error status with a broken chunked body.
2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`_read_capped`): `read(MAX_BODY + 1)` on a response whose `Content-Length` is larger than the bytes actually sent returns the short body without an error. I reproduced it: a 200 that declared 100 bytes and sent 3 came back as `HttpResponse(200, b'abc')`. For JSON calls the parse then fails cleanly, but `report_run` takes a cut-off 2xx as success. Fix: compare the bytes read with `response.length` or the `Content-Length` header, and raise `OSError` when they differ.

REVIEW: FAIL

Review of `brightsky-verify 10 a5af20e85db090ed51c074acc7e38820553d80c3` (spec pass, round 3). Ticket: /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/tasks/10-brightsky-client.md

I read the ticket as it was at a5af20e, when its Answer was still empty. I also read the round 1 and round 2 Review findings, starting from their own headings, which come after the Answer. I did not read the Answer itself.

The range ends at f86efdc, which is the ticket's newest commit and also HEAD, so no later commits were left out. The ticket's Status line goes from open to resolved.

Round 3 is two commits:
- 823eb2d adds tests for control characters in a backend message and for deeply nested JSON bodies.
- f86efdc changes /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py. It catches `RecursionError` in `_json` and `_message`. It replaces characters that are not printable with spaces after scrubbing the token and before the 500-character cut. It also notes on `TIMEOUT` that the 20 s applies to each socket read, not the whole request.

SPEC
- test_brightsky_client.py passes, with the retry cases: 503 then 200, two 503s, 400/401/404/429, and a network OSError retried once: MET (conductor). I read the tests and the assertions match the ticket: `test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep`, `test_two_503s_raise_brightsky_http_error_503_after_two_calls`, `test_a_4xx_raises_after_exactly_one_call_with_no_sleep[400|401|404|429]` and `test_a_network_oserror_is_retried_once`.
- A retried report_run sends a byte-identical body, and a propose whose 503 was stored returns that version after one versions POST: MET (conductor). The tests are `test_a_retried_report_run_sends_a_byte_identical_body` and `test_a_propose_whose_503_was_stored_returns_that_version_with_one_post`. The second asserts the calls were exactly [POST versions, GET detail].
- Bearer token on every request, slug `../x` raises before any call, a queue body that is not an array raises BrightSkyResponseError, one valid entry plus one `../x` entry gives one item and one reason, and the token is in no caplog record: MET (conductor). The tests are `test_every_request_carries_the_bearer_token_json_headers_and_the_timeout`, `test_a_bad_slug_raises_before_any_call`, `test_a_queue_body_that_is_not_a_json_array_raises_a_response_error`, `test_a_queue_with_one_bad_slug_returns_one_item_and_one_reason` and `test_one_log_line_per_request_and_never_the_token_or_a_body`.
- The UrllibTransport loopback test passes with HTTP_PROXY, HTTPS_PROXY and ALL_PROXY set to a dead proxy: MET (conductor). The `dead_proxy` fixture sets all three in upper and lower case and deletes NO_PROXY and no_proxy. A control test shows a plain urllib opener fails under the same settings.
- All existing tests still pass (`python3 -m pytest stepper/tests/unit/ -q`): MET (conductor).
- Acceptance: I ran `python3 -B -m pytest plans/brightsky-verify/acceptance/test_accept_config_client.py -q -p no:cacheprovider` myself, since that file covers this ticket. It printed "34 passed". Every failure the conductor reported is in test_accept_verify_cli.py, which tests ticket 07's CLI. Ticket 07 is not built yet, so those failures do not count against this ticket.
- scope: OK. Over a5af20e..f86efdc the code changes are stepper/brightsky/client.py and stepper/tests/unit/test_brightsky_client.py, both named in Touches. The rest is bookkeeping: the ticket file, one appended line for ticket 10 in plans/brightsky-verify/map.md, and one appended line tagged (10) in plans/brightsky-verify/learnings.md. Nothing from ticket 02 (config, models) or ticket 07 (exit codes, stderr) was changed.
- test first: OK. 960a04f adds only the test file, and its import of `stepper.brightsky.client` fails without the production change; the conductor saw it fail. In this round, 823eb2d adds tests before the fix in f86efdc. The deeply nested body and control-character tests fail on the previous code, which let `RecursionError` through and passed control characters unchanged.

The ticket is already level 3, so there is no level raise. `git status` was clean afterwards and my commands left no files behind.

REVIEW: PASS
