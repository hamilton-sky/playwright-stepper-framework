# Decide how verify treats a version that is not the workflow's current one

Type: settle
Status: resolved
Blocked by: —
Test first: no
Level: 1

The brief asks for `GET /api/workflows/:slug` "(current or a named version)". The
bright-sky backend on `claude/workflow-verify` returns steps only for the current
version: the highest verified, else the highest unverified (`workflows.controller.ts`
`get` → `toDetail` → `currentSteps`). No route returns a named version's steps, and
backend changes are out of scope. So stepper cannot run a version that is not current.

This happens in two places:
- `brightsky verify <slug> --version N` when N is not the current version.
- A `verify --all-unverified` queue entry whose version is not current. This is the
  normal case once a workflow has a verified version and a newer unverified proposal,
  since the verified one stays current.

The user decides. Options:

- **A (recommended): refuse or skip, and do not fail.** `verify <slug> --version N` exits
  3 with `error: <slug> v<N> is not the current version (v<M>); the backend serves only
  the current version's steps`. In `--all-unverified`, such an entry prints
  `<slug> v<N> skipped: not the current version` and does not change the exit code.
  The schedule stays green, and these proposals wait for a human, or for a later
  backend route.
- **B: count it as a failure.** The same messages, but in `--all-unverified` a skipped
  entry makes the exit code 1. The schedule shows red until the backend can serve
  named versions.

Either way nothing is reported to the store for an entry that did not run. A later
bright-sky route for named-version steps would make both options unnecessary; that is a
backend follow-up, not this plan.

What does not depend on the answer is already fixed in spec.md (story "Versions that
are not current"): such an entry or version is never run and nothing is posted for it,
and a single `verify <slug> --version N` exits 3. Only the queue walk's exit code is
open.

## Not in this ticket

- The code: ticket 06 (the queue walk) and ticket 07 (the exit code) build whichever
  answer is chosen.
- Adding the backend route, which is out of scope (bright-sky).

## Done when

- `## Answer` names A or B (or a variant the user gives), with the exit code for each of
  the two places, and the same answer is added as one line to map.md § Decisions so far,
  where the acceptance tests read it.

## Reference

- spec.md § Decisions ("Non-current versions"), § Edge cases
- map.md § Decisions so far (bright-sky facts)
- `/home/claude/bright-sky/backend/src/workflow-store/api/workflows.controller.ts` (read
  only)

## Answer

**Decision: option A** (chosen by the user, "Yes, skips stay green", 2026-11-01).

- `verify <slug> --version N` with N not the current version: nothing is run or posted
  (only the token check and the `GET`), stderr gets
  `error: <slug> v<N> is not the current version (v<M>); the backend serves only the current version's steps`,
  **exit 3**. `--version` equal to the current version runs as if it were not given.
- `verify --all-unverified`, an entry whose version is not current: only its `GET` is
  sent, nothing is posted, it prints `<slug> v<N> skipped: not the current version (v<M>)`,
  and it **does not change the exit code** (exit stays as the other entries make it; a
  queue of only skipped entries exits 0).

- **Built**: no code (settle ticket). Changed this ticket's Status and Answer, and
  appended one `01 —` line to map.md § Decisions so far.
- **Proof**: the Done when is a document check. `grep -n "option A\|^- 01 —" plans/brightsky-verify/map.md`
  shows the decision line in § Decisions so far; this Answer names A with both exit codes.
- **Decisions**: A over B. The verified version stays current while a newer proposal
  waits, so non-current queue entries are the normal case; B would keep the daily
  schedule red for something stepper cannot fix (no backend route serves named-version
  steps, and the backend is out of scope). A keeps red meaning "a run failed or healed".
  Rejected: B (permanent red), and running the current version's steps under the
  queued version's number (would report results against the wrong version).
- **Shortcuts taken**: none.
- **For later tickets**: 06 (queue walk) and 07 (exit codes) build A. Use the message
  forms with the trailing `(v<M>)`, as in spec.md and the acceptance test
  `test_a_queue_entry_that_is_not_current_is_skipped_and_exits_0`
  (`old-flow v1 skipped: not the current version (v2)`); the ticket's option text above
  omits `(v<M>)` on the skip line, and the spec wins. A map.md decision line for this
  already existed in the plan commit; the `01 —` line restates it in the standard form.
