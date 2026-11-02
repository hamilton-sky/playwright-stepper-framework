# Verify a workflow end to end: fetch, map, run, report, and propose a healed version

Type: task
Status: resolved
Blocked by: 10, 11, 13
Test first: yes
Level: 3
Touches: stepper/brightsky/verify.py, stepper/tests/unit/test_brightsky_verify.py, stepper/tests/unit/test_brightsky_heal_loop.py

`stepper/brightsky/verify.py` (new) joins the client (ticket 10), the mapping (ticket 03,
through 13), the executors (ticket 13) and the target conversion (ticket 11). Level 3,
because it decides what the store hears: a `passed` report auto-promotes a version, and a
proposal creates one.

**`async verify_slug(client, executor, slug, *, version=None, headless=True, check_token=True) -> VerifyOutcome`**
0. When `check_token` is true, call `client.queue()` and discard the result. The fetch in
   step 1 is public and never answers 401/403 (map.md), so this guarded call is the only
   way to find a wrong or revoked token before a browser starts. The queue walk passes
   `check_token=False`, since it has just read the queue.
1. `detail = client.get_workflow(slug)`.
2. If `version` is given and is not `detail.current_version`, return
   `VerifyOutcome(status="skipped", reason="not the current version (v<M>)")` and post
   nothing. The outcome is the same whatever the user decides about non-current
   versions; what `skipped` does to the exit code is the CLI's job (ticket 07).
3. `key = new_idempotency_key()`, one per run, reused on the report's retry by the
   client.
4. `map_version(detail)`. On `UnmappableStep(n, reason)`, post a failed `RunReport`
   (step n `failed`, `matched=False`, `tier="unmapped"`; every other step `unchecked`)
   and return `failed` with `reason="step <n>: <reason>"`. Nothing is launched.
5. `executed = await executor.execute(mapped, headless=headless)`.
6. Post `RunReport(version=detail.current_version, steps=[...], result="passed" if every
   step passed else "failed", idempotency_key=key)`. A report that fails
   (`BrightSkyHttpError`) returns `failed` with that reason and skips step 7.
- **401 and 403 are never outcomes.** A `BrightSkyHttpError` with status 401 or 403 from
  any call (step 0, the report, the propose) propagates out of `verify_slug`, so the CLI
  can exit 3 (ticket 07). Every other `BrightSkyHttpError` keeps the handling above.
7. Propose only when at least one step is `healed` and every step is either `passed` or
   `healed`:
   - `steps = copy.deepcopy(detail.steps)`;
   - for each healed step, `target_from_element(healed_element["healed"],
     original=steps[n-1].get("target"))` replaces `steps[n-1]["target"]`, so the
     proposed step keeps its role and, with it, its action (ticket 11). When `healed_element` is None (scroll/wait injection), or
     the element cannot be described, propose nothing and say why in `reason`;
   - `source = "stepper"` when every healed tier is `embed_direct` or `heal_cache`,
     else `"haiku"` (spec § Decisions, "Proposal source");
   - `note = "Healed by stepper run <key> of v<N>: step <n> target <old> -> <new>; ..."`,
     cut to 1000 characters by `Proposal`;
   - `proposed_version = client.propose_version(slug, proposal)`. A propose that fails
     (any `BrightSkyHttpError` but 401/403) leaves the status `healed` with
     `reason="proposal failed: <message>"` and no proposed version, matching how a failed
     report is handled in step 6.
8. The status is `passed` when the report was passed, `healed` when any step healed
   (whether or not a proposal was made), else `failed`.

**`async verify_all_unverified(client, executor, *, headless=True) -> QueueRun`**
- `items, rejected = client.queue()`. Each rejected reason becomes a `failed` outcome
  with slug `"?"`.
- Every item, in the order `queue()` returned it (the backend's, oldest first), with no
  cap (brief, Decided): `verify_slug(..., version=item.version)`, one at a time.
- An exception from one entry (`BrightSkyHttpError`, `BrightSkyResponseError`) becomes
  that entry's `failed` outcome, and the walk goes on, except a 401 or 403, which stops
  the walk and propagates: the token is bad for every later entry too.
- Return `QueueRun(outcomes)`.

**`make_executor() -> StepExecutor`** returns `PipelineExecutor()`, and
**`make_client(config) -> BrightSkyClient`** returns `BrightSkyClient(config)`. The CLI
calls both, and tests monkeypatch them.

**The heal-loop test** (`test_brightsky_heal_loop.py`) is the bar's "a missing element
triggers the heal cascade" proven through the real engine, with no browser and no
network. It uses only the public seams in spec.md § Interfaces:
- a pilot-like workflow with step 2 targeting link "The Hobbit", served by a stubbed
  `Transport`;
- an `EngineExecutor` (ticket 13) over a fake page, with a resolver double that misses
  the stored `{"role": "link", "name": "The Hobbit"}` and finds `{"role": "link",
  "name": "The Hobbit (1937)", "css": "a.result"}`, and an AI double that records
  `task_type`;
- `DOMSnapshotCascade.capture` and `VisualBridge.check` monkeypatched.

## Not in this ticket

- Argument parsing, printing and exit codes; ticket 07.
- The GitHub Actions schedule; its own ticket.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_heal_loop.py -q` passes. Its
  embed_direct case shows a runs POST first, with `result: "failed"` and step 2
  `outcome: "failed"`, `matched: false`, `tier: "embed_direct"`, then one versions POST
  with `source: "stepper"`, the healed target in step 2 (role link, accessibleName
  "The Hobbit (1937)", selectors `["a.result"]`), steps 1 and 3 equal to the fetched
  ones, and a note containing the key and `step 2`.
- In the same file, a case whose `embed_direct` cfg also misses and whose third AI reply
  resolves shows the AI double's `task_type`s as exactly `["heal", "heal", "heal_big"]`,
  step 2 reported with `tier: "big"`, and a versions POST with `source: "haiku"`; and a
  case where every AI reply misses shows a failed report and no versions POST.
- `python3 -m pytest stepper/tests/unit/test_brightsky_verify.py -q` passes. With a fake
  executor and a stubbed transport, its tests show: a full pass posts one runs POST with
  every step `passed`, `matched: true`, a non-empty tier, `result: "passed"`, one
  idempotency key, and no versions POST; a failed step posts `failed`, marks later steps
  `unchecked`, and proposes nothing; an unmappable step posts a failed report with
  `tier: "unmapped"` and executes nothing; a heal plus a later failure proposes nothing.
- In the same file: a non-current `version` returns `skipped` and the transport saw only
  the token check and the GET; the queue walk runs all 12 of 12 entries in the queue's
  order; and one entry raising a 503 does not stop the next.
- In the same file, against the stubbed transport: a 401 on the token check raises
  `BrightSkyHttpError(401, ...)` after exactly one request, with the executor never
  called; a 403 on `POST /runs` raises after the run; and in the queue walk a 401 on the
  first entry's `POST /runs` raises and the second entry is never fetched.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_heal_loop.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_brightsky_verify.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Stories ("Heal and propose", "Walk the queue", "Versions that are not
  current"), § Decisions ("Proposal source", "Queue walk", "Healed means failed"),
  § Edge cases, § Interfaces
- bright-sky `workflow-verification.service.ts` `HEAL_SOURCES` (read only)

## Answer

Work started at commit `67a12c16d7df4d68e7ee57f9ebf3769d0ad521d1`; the failing-test commit is `89ab8e9`.

**Built**
- `stepper/brightsky/verify.py` (new): `VerifyOutcome(slug, version, status, reason="", proposed_version=None)`, `QueueRun(outcomes)`, `async verify_slug(...)`, `async verify_all_unverified(...)`, `make_executor()` (gives `PipelineExecutor()`), `make_client(config)` (gives `BrightSkyClient(config)`).
- `stepper/tests/unit/test_brightsky_verify.py` (new, 32 tests): a fake executor plus a recording stub transport.
- `stepper/tests/unit/test_brightsky_heal_loop.py` (new, 3 tests): the real `EngineExecutor` over a fake page, a resolver double, an AI double that records `task_type`, and `DOMSnapshotCascade.capture` and `VisualBridge.check` monkeypatched.

**Proof** (each run fresh after the last edit)
- `python3 -m pytest stepper/tests/unit/test_brightsky_heal_loop.py -q`: `3 passed`.
  - embed_direct case: the POSTs are `[runs, versions]`. The report has `result: "failed"` and step 2 `{matched: false, tier: "embed_direct", outcome: "failed"}`. The proposal has `source: "stepper"`, step 2's target is `role: link`, `accessibleName: "The Hobbit (1937)"`, `selectors: ["a.result"]`, steps 1 and 3 equal the fetched steps, and the note contains the key and `step 2`. There are no AI calls.
  - big case: `task_types == ["heal", "heal", "heal_big"]`, step 2 has `tier: "big"`, and the proposal has `source: "haiku"`.
  - all-miss case: the same three task types, one POST (runs, `failed`), and no versions POST.
- `python3 -m pytest stepper/tests/unit/test_brightsky_verify.py -q`: `32 passed`. The tests cover:
  - a full pass: one runs POST with every step `passed`, `matched: true` and a non-empty tier, `result: "passed"`, one key, and no versions POST;
  - a failed step: the later steps are `unchecked` and nothing is proposed;
  - an unmappable step: step 2 is `{matched: false, tier: "unmapped", outcome: "failed"}`, the others are `unchecked`, and the executor is never called;
  - a heal plus a later failure: nothing is proposed;
  - a non-current version: the transport saw only `[GET queue, GET detail]` and the outcome is `skipped`;
  - the queue walk: 12 of 12 entries run in order;
  - a 503 on the first entry: the second entry still passes;
  - a 401 on the token check: `status == 401`, the transport saw only `[GET queue]`, and the executor was never called;
  - a 403 on `POST /runs`: it raises after one execute;
  - a 401 on the first entry's `POST /runs` in the walk: it raises, and no request names `second-flow`.
- `python3 -m pytest stepper/tests/unit/ -q`: `2131 passed`. Build (`compileall`) exits 0. Lint (`stepper/main.py validate`) exits 0.
- Acceptance (`plans/brightsky-verify/acceptance`): 104 passed, 57 failed. Every failure I looked at goes through `run_cli`, where argparse rejects `brightsky` (`invalid choice: 'brightsky'`) because that command is ticket 07's. The non-CLI heal tests pass, and so do the 5 `verify_slug`/`verify_all_unverified` Python-interface tests.

**Decisions**
- Step 8, status for "a heal plus another failing step": `failed`, not `healed`. Read literally, the ticket's step 8 ("healed when any step healed") contradicts the acceptance test `test_a_heal_with_another_step_failing_proposes_nothing` (`outcome.status == "failed"`) and the spec story "When a heal succeeded but another step failed, the run is reported failed". So `healed` is used only when every step passed or healed, which is the propose condition, whether or not a proposal is actually made. A heal by scroll/wait injection, an element the store cannot describe, and a failed propose all stay `healed`, as the ticket's parenthesis asks.
- Reasons: a failed report gives `report failed: <HTTP n: message>`. A failed propose gives `proposal failed: <...>`. An undescribable element gives `step <n>: the store cannot describe the healed element {...}: nothing to propose`, which contains "describe" for ticket 07's message. An injection heal gives `step <n> healed by a scroll or wait, so its element did not change: nothing to propose`. A plain failure gives `step <n>: <error>`.
- Note format: `Healed by stepper run <key> of v<N>: step <n> target <role "name" selectors…> -> <…>; …`. `Proposal` cuts it to 1000 characters.
- Queue walk: the rejected entries come first as `VerifyOutcome("?", None, "failed", reason="entry <i>: …")`, then the valid items in queue order. `queue()` drops the rejected entries' positions, but their reasons keep `entry <i>`.
- The original target passed to `target_from_element` is the fetched wire target (`steps[n-1]["target"]`), not `healed_element["original"]`, so a text-entry heal keeps its `textbox` role.
- An unmappable version whose failed report itself fails (other than 401/403) returns `failed` with `step n: …; report failed: …`.

**Shortcuts taken**
- Only `BrightSkyHttpError` from `propose_version` becomes `proposal failed`, as the ticket says. A `BrightSkyResponseError` (a malformed "new version" body) propagates, which ends the entry as `failed` in the walk even though its report was already sent. Upgrade if the backend is ever seen to answer a malformed 201.
- An exception from the executor itself (a browser crash, `DomainNotReadyError`) is neither reported nor caught in the walk, because the ticket names only the two client errors. It ends `--all-unverified` at that entry. Worth catching (and reporting `incomplete`) once real runs show it happening.

**For later tickets**
- 07: `VerifyOutcome.version` is None only for a `?` entry. A `skipped` outcome carries the requested version and has `reason="not the current version (v<M>)"`, so the line reads `<slug> v<N> skipped: <reason>`. A passed outcome has `reason == ""`. A healed one has `proposed_version` set, or a reason when no proposal was made. 401/403 arrive as a raised `BrightSkyHttpError`. Errors from the token check and the fetch (5xx, 404, `BrightSkyResponseError`) propagate out of `verify_slug` for the CLI to map (404 → 3, else 1).
