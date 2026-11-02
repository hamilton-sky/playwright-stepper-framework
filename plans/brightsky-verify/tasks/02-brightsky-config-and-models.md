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
  - `python3 -m pytest stepper/tests/unit/test_brightsky_models.py -q` → `170 passed`
    (round 2; was 100).
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
  - `python3 -m pytest stepper/tests/unit/ -q` → `1760 passed` (round 2).
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
- **Shortcuts taken**: the writers now check every top-level DTO limit (round 2), but
  not the fields inside each `Proposal` step (title ≤ 200, target shape ...): the steps
  are copied from the backend's own `currentSteps`, so the backend's 400 would catch a
  bad one. Worth adding if a caller ever builds proposal steps itself.
- **Review fixes** (round 1, floor guard): removed both `# type: ignore` comments from
  `stepper/tests/unit/test_brightsky_models.py`, without weakening either test.
  The frozen test now assigns through `setattr(config, "token", "other")` and still expects
  `FrozenInstanceError`. The `_step` helper's `title` parameter is typed `object`, because
  the tests deliberately pass non-str titles, so no ignore is needed. Re-proved: the
  models file `100 passed`, packaging `23 passed`, unit suite `1690 passed`, Build and
  Lint exit 0. `git diff 555d159` shows no `type: ignore`/`noqa`/skip in code.
- **Review fixes** (round 2, pair review). Failing tests first in 78102b3 (58 failed),
  then the fix:
  1. major, token with CR/LF: `load_config` refuses a token with any character outside
     `!`..`~` (whitespace, control, DEL, non-ASCII) with
     `BRIGHTSKY_BRIDGE_TOKEN may contain only visible ASCII characters`, no token text.
     Tested with `abc\r\nX-Evil: 1`, `\n`, space, tab, NUL, DEL, `é`; a token of
     printable punctuation is kept as is.
  2. minor, URL shape: a query or fragment (even an empty `?`/`#`), userinfo, any
     whitespace or non-ASCII in the URL, and a bad port (`:abc`, `:99999`, `parts.port`
     now read inside the try) are refused; messages name the variable, not the value.
     A base URL with a path (`https://x/api/`) is still accepted.
  3. minor: `SLUG_PATTERN` is now `^[a-z0-9-]{3,100}\Z`, so `.match`, `.search` and
     `.fullmatch` all refuse `abc\n` (tested for each).
  4. minor, missing writer limits: `RunReport.version` int 1..2147483647 (the DTO's
     `maxVersion`), steps a list of `RunStep`; `RunStep.step_number` int 1..50 (DTO
     `@Max(maxSteps)`), `matched` a bool; `Proposal.steps` a list of 1..50 dicts.
     bool is refused where an int is expected.
  5. minor, `TypeError` instead of `ValueError`: `tier`, `outcome`, `result`, `source`,
     `note` and `idempotency_key` are type-checked first, so non-str values (None, int,
     bytes, list) raise `ValueError`.
  Extra edit inside a Touches file: `test_more_than_50_steps_raises` built step numbers
  1..51, which the new 1..50 cap refuses before the report exists. It now builds 51 steps
  numbered `n % 50 + 1` and matches the stricter `at most 50 steps` (length is checked
  before uniqueness), so it still proves the 50-step limit. Re-proved: models 170 passed,
  packaging 23 passed, unit 1760 passed, Build and Lint exit 0, acceptance config subset
  13 passed.
- **For later tickets**: ticket 10 must re-export `BrightSkyResponseError` from
  `stepper.brightsky.client` (the acceptance tests import it from there) and reuse
  `SLUG_PATTERN` with `fullmatch`. `QueueItem.from_json` errors read like
  `slug must match ^[a-z0-9-]{3,100}$`, ready for ticket 06's `entry <i>: <reason>`.

## Review findings (round 1, floor guard)

floor guard: the diff weakens the bar instead of meeting it
suppress: stepper/tests/unit/test_brightsky_models.py: config.token = "other"  # type: ignore[misc]
suppress: stepper/tests/unit/test_brightsky_models.py: WorkflowDetail.from_json(_detail(currentSteps=[_step(), _step(title)]))  # type: ignore[arg-type]
if a finding is intended, the ticket needs a line like: Floor: allow <category>

## Review findings (round 2, pair review)

I'm failing ticket 02 (brightsky-verify) on one major finding: a bridge token with a line break in it gets through config, and a later step can then print it in full.

**Scope**
- Range reviewed: 555d159..5df595f. 5df595f is the ticket's last commit and is also HEAD, so no later commits were left out.
- I read the ticket as it stood at the base commit, cut at `## Answer`. From the working copy I read only the round-1 "Review findings" section, which comes after the Answer. The Answer itself never reached me.
- The ticket's Status line in the diff changed from `open` to `resolved`.
- Round-1 floor-guard issue: the two `# type: ignore` lines are gone from the test file. I found no skip, xfail, noqa or `assert True` in it.

**Done when, re-run by me**
- `pytest stepper/tests/unit/test_brightsky_models.py -q`: 100 passed.
- `pytest stepper/tests/unit/test_packaging.py -q`: 23 passed.
- `pytest stepper/tests/unit/ -q`: 1690 passed.

**Hostile probing (level 3)**
- BRIGHTSKY_API_URL, all rejected as they should be:
  - `localhost.evil.com`, `127.0.0.1.nip.io`, `localhost@evil.com`, `0x7f000001`, `[::ffff:127.0.0.1]`
  - `ftp://`, `https://`, `http:///localhost`, `http://[::1`
  - No rejection message contains the token, even when the token sits in the URL.
- BRIGHTSKY_BRIDGE_TOKEN: a token with CR/LF in it is accepted (finding 1).
- Reader input (slug, versions, steps, notes): a slug with a trailing `\n` is rejected (fullmatch), a float version is rejected, a bool can't pass as an int, a note that isn't a string is rejected, and error messages name the field without echoing the value.
- Writer constructor arguments: wrong types raise `TypeError` instead of `ValueError`, and some limits aren't checked (findings 4 and 5).

My probe scripts ran from the scratchpad with no bytecode writes, so they left no files in the repo.

QUALITY
1. major stepper/brightsky/config.py: `load_config` accepts a token with CR/LF or other control characters inside it (`"abc\r\nX-Evil: 1"` comes back unchanged; `.strip()` only trims the ends). The stdlib transport that ticket 10 will likely use rejects such a header value and puts the whole value in its exception message: `http.client` raises `ValueError: Invalid header value b'Bearer sekret\nX: y'` (checked). Ticket 07 turns these exceptions into stderr output, so the token would be printed. That breaks the "token appears in no message" guarantee at this boundary. Fix: in `load_config`, reject a token with any whitespace or control character (e.g. require printable ASCII with no spaces), with a message that does not include the token, and add a test.
2. minor stepper/brightsky/config.py: an `api_url` with a query or fragment is accepted (`https://x/?a=1`, `https://example.com#frag`). Ticket 10 will add paths onto the base URL, so the path would land in the query or fragment and the request would go to the wrong endpoint with the token on it. Also accepted: a space in the host (`https://a b`), a bad port (`http://localhost:abc`), and userinfo (`http://user:pw@localhost`), which then shows up in the repr. Fix: reject a query, fragment or userinfo, and read `parts.port` inside the existing try so a bad port is caught.
3. minor stepper/brightsky/models.py: the comment on `SLUG_PATTERN` says to use fullmatch because `$` accepts a trailing newline, but the pattern still has `^...$`. `_slug` uses fullmatch, but ticket 10 may call `.match`. Fix: drop the anchors or use `\Z` so the pattern is safe with any method.
4. minor stepper/brightsky/models.py: the writers don't check everything the backend DTO limits. `RunReport` accepts `version=0`, `RunStep` accepts `step_number=-1` and `matched="yes"`, and `Proposal` doesn't check that it has 1 to 50 steps. Each of these becomes a 400 from the backend instead of a `ValueError` here. Fix: check version ≥ 1, step_number ≥ 1 as an int, matched as a bool, and 1 to MAX_STEPS proposal steps.
5. minor stepper/brightsky/models.py: `tier=5`, `note=None` and `idempotency_key=None` raise `TypeError` from `len()`, not `ValueError`, so a caller that only catches `ValueError` misses them. Fix: check the type first and raise `ValueError`.

REVIEW: FAIL

I reviewed ticket 02 of brightsky-verify, range 555d159..5df595f. 5df595f is both HEAD and the newest commit that touches the ticket, so no later commits were left out. I read the ticket as it stood at the base commit, plus its round 1 findings section by itself; I did not read the `## Answer`. I read the diff with the ticket folder excluded.

SPEC
- test_brightsky_models.py passes, and its config tests cover missing, blank, non-http(s) and http to a non-loopback host, the loopback hosts that are accepted, and that the token is in no message or repr: MET (conductor). I checked the content in the diff: the missing and blank variable tests match exactly `^<VAR> is not set$`. The scheme tests use ftp, file, ws and a URL with no scheme. The non-loopback tests include localhost.example.com and 127.0.0.2, and both groups assert "only sent over https" and that the token is absent. localhost, LOCALHOST, 127.0.0.1 and [::1] are accepted. `TOKEN not in repr/str` is asserted, and `token` is `field(repr=False)`.
- The reader tests cover missing `currentVersion`, 51 steps, a non-str title and a non-int version, each raising `BrightSkyResponseError` that names the field, and `QueueItem` rejects `../x`: MET (conductor). Confirmed in the diff: the tests match on the field (`currentVersion`, `currentSteps`, `currentSteps[1].title`, `currentVersion.version`), and `../x` is in the bad-slug parametrize list.
- The DTO keys for `RunReport` and `Proposal`, a duplicate step number or source `claude` raising `ValueError`, and a 1500-character note cut to 1000: MET (conductor). Confirmed in the diff: the exact-dict assertions for both `to_json()` outputs, the duplicate-step test, `claude` in the source parametrize list, and the 1500-character note asserted to be 1000 characters ending in "…".
- test_packaging.py passes: MET (conductor).
- All existing unit tests pass: MET (conductor).
- Acceptance tests (my own run of `python3 -m pytest plans/brightsky-verify/acceptance/test_accept_config_client.py -q`, which printed 21 failed, 13 passed): every config test this ticket delivers passes (missing/blank variables, frozen config, https-or-loopback refusals, loopback accepted). All 21 failures are `ModuleNotFoundError: No module named 'stepper.brightsky.client'`, which is ticket 10's HTTP client. The verify_cli failures the conductor listed belong to later tickets.
- Round 1 finding (the `# type: ignore` lines that weakened the floor): resolved. Grep finds no `type: ignore` in the test or in `stepper/brightsky/`, and the frozen-config test now uses `setattr`.
- scope: OK. The changed files are the four in Touches (stepper/brightsky/__init__.py, config.py, models.py, stepper/tests/unit/test_brightsky_models.py), plus the plan's learnings.md and map.md entries that the flow expects and the ticket file itself (Status changed from open to resolved). Nothing comes from `Not in this ticket`: no HTTP client, retries or exit codes.
- test first: OK. Commit 8756dd5 adds the test before any code. It imports `stepper.brightsky.config` and `stepper.brightsky.models`, which did not exist then, so it fails without the production change; the conductor saw it fail.

My acceptance run may have left `__pycache__` folders behind. I did not remove anything. The ticket is already level 3, so I did not raise it.

REVIEW: PASS
