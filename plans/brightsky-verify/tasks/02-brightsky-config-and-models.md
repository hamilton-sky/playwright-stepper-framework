# Add the BrightSky config and the validated wire models

Type: task
Status: resolved
Blocked by: —
Test first: yes
Level: 3
Touches: stepper/brightsky/__init__.py, stepper/brightsky/config.py, stepper/brightsky/models.py, stepper/tests/unit/test_brightsky_models.py

Create the package `stepper/brightsky/` beside `stepper/engine/`, not under `sites/`.
`__init__.py` holds only a docstring; `test_packaging.py` needs the file. This ticket is
half of the trust boundary to the backend (the HTTP client is ticket 10): the bridge
token is read here, and untrusted JSON is validated here. So it is level 3. It does no
I/O.

**`config.py`**
- `load_config(environ: Mapping[str, str]) -> BrightSkyConfig`, a frozen dataclass with
  `api_url` (trailing `/` stripped) and `token`.
- It raises `BrightSkyConfigError`:
  - `BRIGHTSKY_API_URL is not set` (missing or blank);
  - `BRIGHTSKY_BRIDGE_TOKEN is not set`;
  - a scheme that is not http/https;
  - `http://` to a host that is not `localhost`, `127.0.0.1` or `::1`. The message says
    the token is only sent over https.
- No message ever contains the token, and `BrightSkyConfig`'s `repr` hides it.

**`models.py`**: dataclasses for the wire, shapes from spec.md § Interfaces and the
bright-sky DTO facts in map.md.
- Readers validate untrusted JSON field by field and raise `BrightSkyResponseError`
  naming the field:
  - `QueueItem.from_json` (slug must match `^[a-z0-9-]{3,100}$`, version int ≥ 1,
    `stepperRuns` int ≥ 0, `createdAt` str);
  - `WorkflowDetail.from_json` (`slug`, `site`, `currentVersion.version` int ≥ 1,
    `currentSteps` a list of 1–50 dicts, each with a str `title`, and `versions` as
    `(version, note)` pairs, where `note` is a str or None).
- `WorkflowDetail.steps` keeps the step dicts as received, so a proposal can copy them
  unchanged.
- `RunStep`, `RunReport` and `Proposal` have `to_json()`. Their constructors enforce:
  - `RunStep`: outcome in `passed|failed|unchecked`, tier ≤ 100 characters or None;
  - `RunReport`: unique step numbers, at most 50 steps, result in
    `passed|failed|incomplete`, idempotency key 1–100 characters;
  - `Proposal`: source in `stepper|haiku`, note ≤ 1000 characters (truncate with `…`).
- `new_idempotency_key()` returns `"stepper-" + uuid4().hex`.
- `SLUG_PATTERN` is the one compiled slug regex; ticket 10 reuses it.

## Not in this ticket

- The HTTP client, the transport, retries and the propose retry check; ticket 10.
- Exit codes and stderr output; ticket 07 maps these exceptions onto exits.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_models.py -q` passes. Its config
  tests show that missing, blank, non-http(s) and http-non-loopback env each raise
  `BrightSkyConfigError` with the message above, that http to `localhost`, `127.0.0.1`
  and `::1` is accepted, and that the token appears in no message and no `repr`.
- In the same file, the reader tests show that a malformed detail (missing
  `currentVersion`, 51 steps, a non-str title, a non-int version) raises
  `BrightSkyResponseError` naming the field, and that `QueueItem.from_json` rejects the
  slug `../x`.
- In the same file, `RunReport.to_json()` and `Proposal.to_json()` produce the DTO keys
  (`version`, `steps[].stepNumber|matched|tier|outcome`, `result`, `client`,
  `idempotencyKey`; `steps`, `source`, `note`), a duplicate step number or a source
  `claude` raises `ValueError`, and a 1500-character note is cut to 1000.
- `python3 -m pytest stepper/tests/unit/test_packaging.py -q` passes, so the new package
  is discoverable.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_models.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_packaging.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Interfaces, § Edge cases, § Decisions ("Token transport")
- map.md § Decisions so far (bright-sky DTO facts)
- `/home/claude/bright-sky/backend/src/workflow-store/api/workflow-store-api.dto.ts` and
  `workflow-store-api.views.ts` (read only)

## Answer

- **Built**: `stepper/brightsky/__init__.py` (docstring only), `stepper/brightsky/config.py`
  (`load_config`, `BrightSkyConfig`, `BrightSkyConfigError`, `LOOPBACK_HOSTS`),
  `stepper/brightsky/models.py` (`SLUG_PATTERN`, `BrightSkyResponseError`, `QueueItem`,
  `WorkflowDetail`, `RunStep`, `RunReport`, `Proposal`, `new_idempotency_key`),
  `stepper/tests/unit/test_brightsky_models.py`. Test-only commit 8756dd5 first (failed
  at collection: `ModuleNotFoundError: No module named 'stepper.brightsky'`).
- **Proof**:
  - `python3 -m pytest stepper/tests/unit/test_brightsky_models.py -q` → `100 passed`.
    Config tests: missing and blank (`""`, `"   "`, `"\t\n"`) for both variables raise
    `^<NAME> is not set$`; `ftp://`, `file://`, `ws://` and a scheme-less URL, and http
    to `bright-sky.example.com`, `10.0.0.5`, `localhost.example.com`, `127.0.0.2` raise
    with "only sent over https" and "localhost, 127.0.0.1 and ::1", token absent; http to
    `localhost`, `LOCALHOST`, `127.0.0.1`, `[::1]` and https are accepted; token in no
    `repr`/`str`; frozen; trailing `/` stripped.
  - Readers: missing/null `currentVersion` → `currentVersion`; non-int version
    (0, "2", None, True, 2.0) → `currentVersion.version`; 51 steps → `currentSteps`;
    non-str title → `currentSteps[1].title`; `QueueItem.from_json` with slug `../x`
    (and 6 other bad slugs) → `slug`.
  - Writers: `RunReport.to_json()` = `version, steps[].stepNumber|matched|tier|outcome,
    result, client, idempotencyKey`; `Proposal.to_json()` = `steps, source, note`;
    duplicate step number and source `claude` raise `ValueError`; a 1500-char note
    becomes 1000 chars ending in `…`.
  - `python3 -m pytest stepper/tests/unit/test_packaging.py -q` → `23 passed`.
  - `python3 -m pytest stepper/tests/unit/ -q` → `1690 passed`.
  - Also: Build (`compileall`) exit 0, Lint (`main.py validate`) exit 0, and the
    acceptance config tests (`-k "load_config or https"`) `13 passed`.
- **Decisions**:
  - Reader messages name the field and the rule, never the value received, so a
    response body cannot carry text into a log through an error.
  - Slugs are checked with `SLUG_PATTERN.fullmatch` (a bare `$` accepts a trailing
    newline). `WorkflowDetail.slug` is checked against it too, since later tickets put
    it in URLs.
  - `bool` is refused where an int is expected (`True` is not a version).
  - Both env values are `.strip()`ped; `api_url` then loses trailing `/`. A URL with no
    host (`https://`) raises `BRIGHTSKY_API_URL has no host`.
  - Both errors subclass `Exception`, not `ValueError`, so the writers' `ValueError`
    (a stepper bug) stays distinct from a bad backend body or bad env.
  - `Proposal` truncates in `__post_init__` (via `object.__setattr__` on the frozen
    dataclass), so `proposal.note` is the value sent and the propose retry check
    (ticket 10) compares against what the backend stored.
- **Shortcuts taken**: writers check only the limits the ticket lists. `RunReport.version`,
  `RunStep.step_number` and `Proposal.steps` (1–50, title ≤ 200 ...) are not checked here;
  the backend's 400 would catch them. Worth adding if a caller ever builds them from
  untrusted data.
- **For later tickets**: ticket 10 must re-export `BrightSkyResponseError` from
  `stepper.brightsky.client` (the acceptance tests import it from there) and reuse
  `SLUG_PATTERN` with `fullmatch`. `QueueItem.from_json` errors read like
  `slug must match ^[a-z0-9-]{3,100}$`, ready for ticket 06's `entry <i>: <reason>`.
