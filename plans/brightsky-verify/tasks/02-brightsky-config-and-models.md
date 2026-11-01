# Add the BrightSky config and the validated wire models

Type: task
Status: open
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
