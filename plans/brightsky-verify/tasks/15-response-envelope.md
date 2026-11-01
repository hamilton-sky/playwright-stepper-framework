# Read bright-sky's response envelope and error bodies in the client

Type: task
Status: open
Blocked by: 10
Test first: yes
Level: 3
Touches: stepper/brightsky/client.py, stepper/tests/unit/test_brightsky_client.py, stepper/tests/unit/test_brightsky_verify.py

Ticket 09's first manual run stopped here. Its output:

```
brightsky request method=GET path=/api/workflows/verification-queue status=200 attempt=1 duration_ms=18
error: the verification queue must be a list
```

The plan's map read the workflow-store controllers but missed two global layers that sit
in front of them. Ticket 10's client and every offline stub read bare bodies, so the unit
bar could not catch the gap. This ticket makes `stepper/brightsky/client.py` read what the
backend actually sends. The models, `verify.py` and `cli.py` stay as they are.

**What the backend sends.** These facts were read from the bright-sky checkout
(`/home/claude/bright-sky`, branch `claude/workflow-verify`, HEAD 3538079, read only):

- **Success bodies are wrapped.** `/home/claude/bright-sky/backend/src/main.ts` installs
  `TransformInterceptor` globally
  (`/home/claude/bright-sky/backend/src/common/interceptors/transform.interceptor.ts`).
  It returns every handler's result as `{"success": true, "data": <result>, "timestamp":
  "<ISO>"}` unless the route or controller is marked `@SkipTransform()`. Only
  `auth.controller.ts` uses that mark. `WorkflowsController`
  (`/home/claude/bright-sky/backend/src/workflow-store/api/workflows.controller.ts`) is
  not marked, so the queue, the workflow detail, `POST /runs` and `POST /versions` are all
  wrapped. Ticket 09 saw it on the live backend: the queue came back as a dict with the
  keys `data`, `success` and `timestamp`, and `data` was a list of one.
- **Error bodies are not wrapped. Their `message` is nested.** `AllExceptionsFilter`
  (`/home/claude/bright-sky/backend/src/common/filters/all-exceptions.filter.ts`)
  writes `{"statusCode", "timestamp", "path", "message"}`, and its `message` is
  `HttpException.getResponse()`. In NestJS 11.0.14 (`HttpException.createBody`, in
  `/home/claude/bright-sky/backend/node_modules/@nestjs/common/exceptions/http.exception.js`)
  that value takes three shapes:
  - A built-in exception made from a string, such as `NotFoundException('Workflow not found:
    x')` or `UnauthorizedException('Invalid or revoked bridge token')` from the bridge guard,
    gives an object: `{"message": "<text>", "error": "<phrase>", "statusCode": <n>}`.
  - A `ValidationPipe` 400 gives the same object with a list of strings as its `message`.
  - `ThrottlerException` gives a plain string, `"ThrottlerException: Too Many Requests"`
    (`@nestjs/throttler` 6.4.0). So does any error that is not an `HttpException`:
    `"Internal server error"`.

  Today `_message` reads only a top-level string or list. A nested message falls back to
  the reason phrase, so the CLI would print `bridge token rejected (HTTP 401):
  Unauthorized` instead of the backend's text. That breaks spec.md § Edge cases: "the
  status and the backend's `message` are reported".

**The change, in `client.py` only:**

1. Add one private reader for a 2xx body. `queue()`, `get_workflow()` and
   `propose_version()` call it on the parsed JSON before the list check and the models
   readers. If the body is a JSON object with a `success` key, `success` must be `true` and
   `data` must be present, and `data` becomes the body. `success` that is not `true`
   raises `BrightSkyResponseError` naming `success`. A missing `data` raises one naming
   `data`. Neither error is retried: the status was 2xx. A body with no `success` key is
   read as it is. `report_run` still ignores its response body.
2. In `_message`, the backend's message may be a top-level string or list of strings (as
   today), or an object whose `message` is a string or list of strings. A list is joined
   with `"; "`, as today. Anything else falls back to the reason phrase, as today. The
   token scrub, the printable-only pass and the `MAX_MESSAGE` cut still run on the result.

**Why tolerant (the fork).** There are two ways to read the envelope.

- **A, chosen: unwrap when the envelope is present, read a bare body as it is.** The real
  backend works. The bare-body stubs in four unit test files and in the acceptance harness
  keep passing unchanged. No backend view has a `success` key (`WorkflowDetail`, the
  `VerificationQueueItem` list, `WorkflowVersionView` in
  `/home/claude/bright-sky/backend/src/workflow-store/api/workflow-store-api.views.ts`),
  so the two shapes cannot be confused. Validation stays field by field.
- **B, rejected: require the envelope on every 2xx.** Every bare-body stub would have to
  change, including `plans/brightsky-verify/acceptance/bs_harness.py`. Only the tester
  may change that file (the floor guard flags `acceptance-edit`), so B would need a po
  question. It also proves no behaviour the backend shows that A misses.

A third way, `@SkipTransform()` on the workflow-store controllers, would change bright-sky,
and bright-sky is read only to this plan.

**Tests first:**

- `test_brightsky_client.py`:
  - `queue()` of an enveloped list with one valid entry returns that item.
  - An enveloped body whose `data` is not a list raises "must be a list".
  - `get_workflow()` of an enveloped detail returns its `current_version` and steps.
  - `propose_version()` of an enveloped version view returns its number.
  - An envelope with `"success": false`, and one with no `data`, each raise
    `BrightSkyResponseError` naming the field, after exactly one call.
  - Errors in the filter's shape:
    - a 404 whose nested `message.message` is `"Workflow not found: x"` raises
      `BrightSkyHttpError(404, "Workflow not found: x")`;
    - a 400 whose nested message is a list is joined with `"; "`;
    - a 429 with a top-level string message keeps that string;
    - a nested message that contains the token comes back with `<token>` in its place.
- `test_brightsky_verify.py`: one `verify_slug` full pass where the stub wraps every 2xx
  body exactly as the backend does: queue, detail, and the `POST /runs` view. The outcome
  is `passed`, and exactly one `POST /runs` goes out, with one idempotency key and three
  `passed` steps.

## Not in this ticket

- Any bright-sky change, including `@SkipTransform()`.
- Changing the existing bare-body stubs, or anything under `plans/brightsky-verify/acceptance/`.
- Running the manual check. That is ticket 09.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_client.py stepper/tests/unit/test_brightsky_verify.py -q`
  passes, with the envelope tests and the error-shape tests listed above. Before the
  change, the enveloped-queue test fails with "must be a list" and the nested-404 test
  fails because the message is `Not Found`.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.
- The acceptance suite still passes: `python3 -m pytest plans/brightsky-verify/acceptance -q`.
- When resolving, add one line to map.md § Decisions so far that records the envelope and
  the error shape, with the bright-sky file names above.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_client.py stepper/tests/unit/test_brightsky_verify.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
$ python3 -m pytest plans/brightsky-verify/acceptance -q
prints passed
```

## Reference

- tasks/09-acceptance.md § Answer and § Attempt note (the live run and the shapes it saw)
- tasks/10-brightsky-client.md (the client's retry policy, which is unchanged)
- spec.md § Edge cases (4xx row, malformed-response row), § Interfaces (`BrightSkyClient`)
- learnings.md, the (09) line

## Answer

