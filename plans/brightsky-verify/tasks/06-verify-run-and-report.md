# Verify a workflow end to end: fetch, map, run, report, and propose a healed version

Type: task
Status: open
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
