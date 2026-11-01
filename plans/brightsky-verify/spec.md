# brightsky-verify — Spec

## Problem

BrightSky's workflow store (bright-sky PR #26, branch `claude/workflow-verify`) can now
auto-promote a workflow version once a stepper run passes it, exposes a verification
queue of unverified versions, and seeds an unverified Open Library pilot
(`openlibrary-find-author`). Nothing runs those workflows yet, so every version stays
unverified and the user has to check each one by hand.

The user agreed on 2026-10-26: "Claude drafts the first golden steps, stepper runs them,
small failures get a free exact-match fix first, then Haiku, then the big model; a version
that passes a full run becomes verified automatically, anything else waits for your OK."
The user approved the plan B brief on 2026-10-29. That brief splits the work into the
backend plan, which is done, and this one, the stepper half.

## Goal and the bar

Stepper gets a `brightsky` adapter. It fetches a workflow version from the BrightSky
backend with a bridge token (client `stepper`), maps its steps to stepper steps, runs them
headless through the existing pipeline, and reports the run back. When a step's element
cannot be found, the existing heal cascade tries to fix it. A fixed version is proposed
back to the store as unverified, and the run that needed the heal is reported as failed.
A CLI command and a GitHub Actions schedule drive the adapter.

The bar:

- Unit tests (no network, no browser) with a fake BrightSky HTTP server or a stubbed
  transport show:
  - the step mapping for each target kind;
  - a full pass reports every step passed with one idempotency key;
  - a missing element triggers the heal cascade, a version is proposed with a source and
    a note, and the run is reported as failed;
  - missing env gives exit 3 with a message;
  - a 5xx is retried once and a 4xx is not.
- `python3 -m pytest stepper/tests/unit/` passes, and all existing tests still pass.
- Manual check against a locally running bright-sky backend on branch
  `claude/workflow-verify`: `python3 -m stepper brightsky verify openlibrary-find-author`
  exits 0, and the workflow then shows a verified current version.

## Stories

### Verify one workflow

**As** the store owner, **I want** `python3 -m stepper brightsky verify <slug>` to run a
workflow's current version and report it, **so that** a version that works is verified
without me.

- [ ] With `BRIGHTSKY_API_URL` and `BRIGHTSKY_BRIDGE_TOKEN` set and every step passing,
      the command posts one run report with `result: "passed"`. Every step in it has
      `outcome: "passed"`, `matched: true` and a non-empty `tier`, and the report carries
      one `idempotencyKey`. The command exits 0.
- [ ] When a step fails and is not healed, the report has `result: "failed"` and that step
      has `outcome: "failed"`. Steps after the hard stop have `outcome: "unchecked"`. No
      version is proposed. The command exits 1.
- [ ] When either variable is missing or blank, the command prints
      `error: BRIGHTSKY_API_URL is not set` (or `BRIGHTSKY_BRIDGE_TOKEN`) to stderr, makes
      no HTTP request, and exits 3. No traceback is shown.
- [ ] When the slug is malformed (it does not match `^[a-z0-9-]{3,100}$`), or the
      backend answers 404 to the fetch, the command prints `error: ...` naming the
      problem and exits 3.
- [ ] A wrong or revoked token is caught before any browser run.
      `GET /api/workflows/:slug` is public and never answers 401/403 (map.md), so
      `verify <slug>` first makes one guarded call, `GET /api/workflows/verification-queue`,
      and only then fetches the workflow. A 401 or 403 there prints
      `error: bridge token rejected (HTTP <status>): <backend message>` to stderr, sends
      no other request, launches no browser, and exits 3. The stubbed transport sees
      exactly one request, and the token is not in the output.
- [ ] A 401 or 403 on `POST /runs` or `POST /versions` (a token revoked mid-run) prints
      the same `bridge token rejected` error and exits 3. In `--all-unverified` it stops
      the walk there: no later entry is run.
- [ ] Passing both a slug and `--all-unverified`, or neither, prints a usage error and
      exits 3.

### Heal and propose

**As** the store owner, **I want** a step whose element moved to be healed and proposed
as a new version, **so that** I only review a small change instead of rewriting the step.

How a tester reaches the heal loop without a browser or a network, through the public
seams under Interfaces: run `verify_slug` (or the CLI with `make_executor` and
`make_client` monkeypatched) with a stubbed `Transport` that serves the workflow and an
`executor.EngineExecutor(page, resolver, ai_service=...)`. Its `resolver` double answers
not-found for the stored target and found for the healed one, its `ai_service` double
records each `task_type` it is asked for, and the two page probes the heal loop calls,
`DOMSnapshotCascade.capture` and `VisualBridge.check`, are monkeypatched to return a
`DomPayload` and `None`. Everything below is then visible in the run and proposal
payloads the transport records, in the AI double's `task_type` list, and in the CLI's
output and exit code.

- [ ] Every acting step `map_version` returns (`click`, `fill`) has
      `extra["strict"] is True`. Through `EngineExecutor`, the resolver double is asked
      for the stored target with `strict=True`, so the description-driven fallbacks never
      stand in for it, and a miss on that target is what starts the heal loop.
- [ ] Heal order per step, seen as the AI double's `task_type` list and the healed step's
      `tier` in the run payload:
  - the probe gives an `embed_direct` cfg that resolves: no AI call, tier
    `embed_direct`;
  - the probe gives no cfg: `["heal"]` and tier `cheap` when that reply resolves;
  - the probe gives an `embed_direct` cfg that misses, and every AI reply misses:
    exactly `["heal", "heal", "heal_big"]`. The failed `embed_direct` try does not count
    as one of the two cheap tries, so `heal_big` is never asked for before two `heal`
    calls have failed;
  - the same with a third reply that resolves: tier `big`;
  - after the `embed_direct` miss, the probe is asked with `skip_direct=True`, and every
    `heal` and `heal_big` prompt the AI double records contains the content of the
    payload it returned for that call (the page, not an empty `dom`).
- [ ] The strict order is the BrightSky executors' only. `StepRunner` and `RunConfig`
      default to `strict_heal_order=False`, and with the default a `run --heal N` heals
      exactly as before: an `embed_direct` cfg is retried on every attempt with no AI
      call, the probe is never asked with `skip_direct`, and `heal_big` is never asked
      for.
- [ ] When the heal succeeds and every other step passes, the run is reported first, with
      `result: "failed"`. The healed step has `outcome: "failed"`, `matched: false` and
      `tier` naming the rung (`embed_direct`, `cheap` or `big`). The CLI prints
      `<slug> v<N> healed -> proposed v<M>` and exits 1.
- [ ] After that report, exactly one `POST /api/workflows/<slug>/versions` is sent. It
      carries the fetched version's steps with only the healed steps' `target` replaced,
      `source: "stepper"` when every heal was `embed_direct`, `source: "haiku"` when any
      heal used an AI rung, and a `note` naming the run's idempotency key, the version it
      ran and, for each healed step, its number and its old and new target.
- [ ] A proposed step keeps its action. A text-entry step (target role `textbox`, an
      `url_change` outcome) healed to a role-less element such as `{"placeholder":
      "Search"}` is proposed with the original `role` (and no accessibleName) beside the
      new selector, so `map_version` on the proposed steps maps it to a `fill` of the
      same value, not a `click`, whose element cfg is the healed selector alone.
- [ ] A healed step is never reported as passed in the same run. Decided in the brief:
      "A healed step must not count as passed in the BrightSky run report, even though
      StepRunner's _heal_succeeded treats healed as passing for its own summary."
- [ ] When a heal succeeded but another step failed, the run is reported failed and
      nothing is proposed.
- [ ] With no AI key in the environment (an `EngineExecutor` built without an
      `ai_service`, so it uses a real `AIService`), only `embed_direct` can heal. A step
      the probe gives no cfg for stays `failed` in the run payload, nothing is proposed,
      and the CLI exits 1. `AIService().chat(..., task_type="heal_big")` with
      `ANTHROPIC_API_KEY` unset raises `RuntimeError` and makes no request.

### Walk the queue

**As** the store owner, **I want** `verify --all-unverified` to work through the
verification queue, **so that** a schedule can keep the store verified.

- [ ] The command reads `GET /api/workflows/verification-queue` and runs every entry, one
      at a time, in the order the backend returns them (oldest first), with no cap
      (brief, Decided). It prints one line per entry: `<slug> v<N> passed`, `failed`,
      `healed` or `skipped`, with a reason after a colon when there is one.
- [ ] An entry that raises (a 5xx after the retry, a malformed detail) prints as
      `failed` and the walk goes on to the next entry. A malformed queue entry (a bad slug,
      a version that is not an integer ≥ 1) prints as `? failed: entry <i>: <reason>`.
- [ ] Exit 0 when every run passed (or the queue was empty), and exit 1 when any run
      failed or was healed.

### Versions that are not current

The backend serves steps only for a workflow's current version (map.md), so stepper
cannot run any other. Seen through a stubbed transport and the CLI:

- [ ] `verify <slug> --version N`, where N is not the `currentVersion` the fetch returns,
      sends only the token check and that `GET`: no run report and no proposal. It prints
      `error: <slug> v<N> is not the current version (v<M>); the backend serves only the
      current version's steps` to stderr and exits 3. `--version` equal to the current
      version runs as if it were not given.
- [ ] In `verify --all-unverified`, an entry whose version is not current sends only its
      `GET`, nothing is posted for it, and it prints
      `<slug> v<N> skipped: not the current version (v<M>)`.
- [ ] The one open point is what a skipped entry does to the queue walk's exit code,
      which is the user's choice in ticket 01. Under option A it leaves the exit code as
      the other entries make it (a queue of one skipped entry exits 0). Under option B it
      makes the exit code 1. The answer is recorded in ticket 01's `## Answer` and as a
      line in map.md § Decisions so far, and the acceptance test for this criterion
      asserts that option.

### Run on a schedule

**As** the store owner, **I want** a GitHub Actions workflow to run the queue daily,
**so that** verification happens without me starting it.

- [ ] `.github/workflows/brightsky-verify.yml` runs on a daily `schedule` and on
      `workflow_dispatch`. It runs `python -m stepper brightsky verify --all-unverified`
      headless, with `BRIGHTSKY_API_URL` and `BRIGHTSKY_BRIDGE_TOKEN` taken from repo
      secrets.
- [ ] When either secret is unset, the job emits a `::notice` that names both secrets,
      skips every later step, and ends green.

## Scope

In:
- `stepper/brightsky/`, a new package beside `stepper/engine/` (not under
  `stepper/sites/`, since it is not a site). It holds the config, the HTTP client, the
  step mapping, the executor and the verify loop.
- One more escalation entry in AIService/providers for the big model, and the strict heal
  order, opt-in and switched on only by the BrightSky executors: StepRunner's heal loop
  tells the healer which rungs it has already tried for the step, a failed
  `embed_direct` try is free, and after it `DOMSnapshotCascade.capture` is asked to skip
  its `embed_direct` shortcut so the AI rungs see the page.
- `StepRunner.add_hook`, so the adapter can attach its per-step outcome checks.
- The `brightsky verify` CLI command, the scheduled GitHub Actions workflow, and a
  README/ARCHITECTURE section.

Not in scope:
- Any bright-sky backend change (done in PR #26). In particular, the backend has no
  route that returns a non-current version's steps (see "Versions that are not current").
- Running through the mailbox on the owner's Mac, and logged-in sites (GitHub, GCP).
- A new healer or resolver. The heal cascade (DOMSnapshotCascade, AiHealer, AIService)
  is reused, with only the small opt-in additions the brief allows (`heal_big`,
  `skip_direct`, the strict order).
- Claude drafting new flows on demand; that is plan C.

## Happy path

1. `python3 -m stepper brightsky verify openlibrary-find-author`. The CLI loads `.env`,
   reads the two variables and validates the slug. `GET
   /api/workflows/verification-queue` answers 200, so the token is accepted (the body is
   not used here).
2. `GET /api/workflows/openlibrary-find-author` returns `currentVersion` and
   `currentSteps`. The response is validated field by field before anything uses it.
3. The mapping turns the three steps into stepper steps:
   - a `navigate` to `https://openlibrary.org/`;
   - `fill` of the textbox "Search" with "The Hobbit" and press Enter;
   - `click` of the link "The Hobbit";
   - `click` of the link "J.R.R. Tolkien".
   Every acting step is strict, and each carries its expectation (the URL it starts on,
   the URL it must reach).
4. The executor runs them headless through `prepare_run` → `build_session_set` →
   `build_pipeline` → `execute_pipeline`, with healing at 3 paid attempts (plus the free
   `embed_direct` try) and the heal cache off. A recording resolver notes which resolver tier matched each step, and an
   expectation hook checks each step's outcome after it runs.
5. Every step passes. The client posts `POST /api/workflows/openlibrary-find-author/runs`
   with `version`, three `passed` steps, `result: "passed"`, `client: "stepper"` and one
   idempotency key.
6. The backend auto-promotes the version. The CLI prints
   `openlibrary-find-author v1 passed` and exits 0.

## Edge cases

| Trigger | Expected behaviour | Handled in ticket |
|---|---|---|
| `BRIGHTSKY_API_URL` or `BRIGHTSKY_BRIDGE_TOKEN` missing or blank | `error: <NAME> is not set`, no request, exit 3 | 02, 07 |
| `BRIGHTSKY_API_URL` is `http://` to a non-loopback host, or not http(s) | `error:` saying the token is only sent over https (http is allowed for localhost, 127.0.0.1 and ::1), exit 3 | 02 |
| 5xx or network error / timeout on the token check, the queue read or the fetch | one retry after a backoff; a second failure prints `error: ...` to stderr and exits 1 | 10, 07 |
| 5xx or network error / timeout on `POST /runs` or `POST /versions` | one retry after a backoff; a second failure makes that workflow's line `<slug> v<N> failed: <reason>` (or `healed: proposal failed: <reason>` for a propose), and the command exits 1; in `--all-unverified` the walk goes on | 10, 06, 07 |
| 4xx | not retried; the status and the backend's `message` are reported. A 404 on the fetch exits 3, and any other 4xx except 401/403 exits 1 | 10, 07 |
| 401/403 on the token check, the queue read, `POST /runs` or `POST /versions` | `error: bridge token rejected (HTTP <status>): ...`, exit 3; on the token check no browser is launched; in the queue walk no later entry runs | 06, 07 |
| A propose POST failed with a 5xx after the server stored it | before retrying, the client re-reads the workflow; if a version with the same note exists, it is taken as the result, so no duplicate is created | 10 |
| A malformed backend response (wrong types, more than 50 steps, missing `currentVersion`) | `error:` naming the field, nothing is run, exit 1 | 02, 10 |
| A step with no target, a combobox/listbox/slider role, a textbox with no quoted value, an unknown matchMode, or a navigate host other than the workflow's `site` | the run fails with `step N: <reason>`, nothing is launched, and a failed run report is posted (that step `failed`, the others `unchecked`), exit 1 | 03, 06 |
| A stored value that starts with `ENV:` / `${ENV:`, or any mapped text containing `{{` | unmappable (the engine would otherwise type the runner's env, such as the bridge token, into the page, or fail on an unresolved reference) | 03 |
| `matchMode: "regex"` that does not compile | it falls back to `startsWith`, the same as BrightSky's `matchUrl` | 03, 05 |
| A step's outcome is not met (for example, the URL never contains `/search`) | the step is failed with `expected outcome not met: ...`, `matched: true` | 05 |
| The page is not on the step's `expectedUrl` before it acts | the step is failed before it acts, `matched: false` | 05 |
| A heal whose new element has no role+name, no css, no xpath and no id (only text) | the run is reported failed; nothing is proposed; the CLI says the store cannot describe the healed element | 11, 06 |
| A step healed by scroll/wait injection, so its element did not change | the run is reported failed; nothing is proposed | 06 |
| `verify <slug> --version N` for a non-current N | only the token check and the GET are sent; `error: <slug> v<N> is not the current version (v<M>); ...`, exit 3 | 06, 07 |
| A queue entry whose version is not current | only its GET is sent; `<slug> v<N> skipped: not the current version (v<M>)`; its effect on the exit code is ticket 01's answer (A: none, B: 1) | 01, 06 |
| A queue entry with a malformed slug or version | it is printed as `? failed: entry <i>: <reason>`, the walk goes on, and the exit code is 1 | 10, 06 |
| An `embed_direct` cfg that misses | it is a free try; the cheap tier is still tried twice before the big model | 12 |
| `ANTHROPIC_API_KEY` unset | the big-model rung raises inside the heal loop, and a step the cheap tier could not fix stays failed | 04, 12 |
| The scheduled job without secrets | a `::notice`, later steps skipped, job green | 08 |

## Design

```
 CLI: brightsky verify <slug> | --all-unverified        (07)
   │ argv
   ▼
 verify.py  verify_slug / verify_all_unverified         (06)
   │ GET detail / queue          ▲ RunReport, Proposal
   ▼                             │
 client.py  BrightSkyClient ─────┘  urllib, 1 retry     (10)
   │ WorkflowDetail (models.py, config.py)              (02)
   ▼
 mapping.py  map_version ──► MappedWorkflow             (03)
   │ StepConfigs + expectations      └─► UnmappableStep ──► failed report
   ▼
 executor.py  PipelineExecutor | EngineExecutor         (13)
   │ prepare_run ─► build_pipeline ─► execute_pipeline
   │   RecordingResolver (tier)  ExpectationHook (outcome) (05)
   ▼
 StepRunner ── element not found ──► _run_heal_loop      (12)
   │   strict order, BrightSky runs only (strict_heal_order=True):
   │   free:     embed_direct (once, if the DOM gave a cfg)
   │   then capture(skip_direct=True): candidates with page content (14)
   │   paid 1-2: cheap chain  (task "heal": groq/gemini/haiku)
   │   paid 3:   big model    (task "heal_big", Sonnet-class) (04)
   ▼ StepResults
 ExecutedStep[] ─► verify.py: healed => report failed,
                   then propose(source, note)           (06)
                   targets.py target_from_element       (11)
```

### Decisions

- **HTTP client.** Options: stdlib `urllib.request`, or adding `requests`/`httpx`.
  Chosen: `urllib`. Why: `requirements.txt` has no HTTP library, the client makes four
  kinds of call, and a new dependency would have to be pinned for CI and the web image.
  Rejected: `requests`.
- **How a run is driven.** Options: the existing pipeline pieces (`prepare_run`,
  `build_session_set`, `build_pipeline`, `execute_pipeline`) fed a temporary workflow
  file, or a StepRunner assembled by hand in the adapter. Chosen: the pipeline pieces.
  Why: they already do plan validation, preflight, reporters, sessions and healer wiring,
  and `prepare_run` takes a `resolver=`. Rejected: hand assembly, which would copy
  `build_pipeline`.
- **Where outcome checks run.** Options: a `StepHook` attached through a new public
  `StepRunner.add_hook(domain, hook)`; a new registered `brightsky_expect` action
  appended after each step; or running steps one at a time and checking between calls.
  Chosen: the hook. Why: hooks already see the final result after retries and healing
  and may amend it (runner/hooks.py), and replacement runners in the heal loop share the
  hooks, so a heal that misses the outcome is not a heal. Rejected: the action, because
  `prepare_run` validates the plan against the registry before the adapter could
  register it; one-at-a-time, because the healer would lose the nearby-step context
  `AiHealer` puts in its prompt.
- **Heal order.** The brief decides it: exact-match (`embed_direct`, free) first; if it
  gives no cfg or its cfg also misses, the cheap tier (the configured groq/gemini/haiku
  `heal` chain); the big model only after two cheap-tier AI calls have failed for that
  step. "An embed_direct retry never counts as a cheap-tier attempt." Today
  `AiHealer.heal` returns the `embed_direct` cfg on every attempt whenever the DOM
  capture has one, so a cfg that misses is retried until the attempts run out and the AI
  is never asked. Two ways to make the order strict:
  - (a) StepRunner's heal loop keeps the rungs it has tried for the step and passes them
    to the healer as `tried`. `HealerStrategy.tier_for(dom, tried)` names the next rung,
    and `AiHealer.heal(..., tried=...)` routes on it. One `embed_direct` try per step is
    free: it does not use up one of `max_heal_attempts`.
  - (b) AiHealer counts its own calls per step.
  Chosen: (a). Why: `HealerStrategy`'s contract says implementations are stateless across
  calls, and only the loop knows when one step's healing ends. Rejected: (b). Also
  rejected: raising the hard cap from 3 to 4 so the free try fits inside it, because
  `test_max_heal_attempts_is_capped_at_three` pins the cap and the free try is not a
  paid attempt. Verify runs use `max_heal_attempts=3`, so the big rung exists.
  The brief also decides two more things here. After the free try has missed, the AI
  rungs must see the page, so `DOMSnapshotCascade.capture` gains `skip_direct=True`,
  which returns the candidates payload (with content) instead of the empty
  `embed_direct` one, and the strict loop passes it from then on. And the strict order is
  opt-in: `strict_heal_order=False` is the default on `StepRunner` and `RunConfig`, only
  `EngineExecutor` and `PipelineExecutor` set it, and `run --heal N` and CI's heal jobs
  (`sd_heal_test`, `sd_full_heal_flow`) behave as today.
- **Big model id.** Options: `claude-sonnet-5-5` as one module constant, or an env var
  to choose it. Chosen: the constant `_BIG_MODEL = "claude-sonnet-5-5"` in
  `stepper/engine/ai/service.py`. Why: there is one caller and no ask for
  configurability. The repo's other Sonnet id, `claude-sonnet-4-20250514` (ClaudePlanner's
  default), is retired, so it is not reused (map.md has the source). Rejected: an env
  var, and reusing the retired id.
- **Recording which rung healed.** Options: a non-abstract
  `HealerStrategy.tier_for(dom, tried) -> str` that AiHealer uses both to route and to
  name the rung, and that StepRunner writes into `healed_element["tier"]`; or the healer
  writing the tier into the replacement step's `extra`. Chosen: `tier_for`. Why: one
  source of truth for routing and naming. Rejected: `extra`, because
  `test_the_fast_path_changes_the_selector_and_nothing_else` pins `extra` unchanged and
  the key would leak into actions.
- **Proposal source.** Options for a big-model heal: `haiku` or `claude`. Chosen:
  `embed_direct` (or `heal_cache`) only → `stepper`; any AI rung → `haiku`. Why: the
  brief names `stepper` and `haiku`. Also, bright-sky's `HEAL_SOURCES` (`stepper`, `haiku`) need two passing
  runs with distinct idempotency keys before promotion, while `claude` needs one
  (`workflow-verification.service.ts`). Labelling a big-model heal `claude` would weaken
  the gate. Rejected: `claude`.
- **Healed means failed.** From the brief's Decided line, quoted under Stories. The
  adapter maps `StepResult.status == "healed"` to `outcome: "failed"` and leaves
  `_heal_succeeded` alone.
- **Strict acting steps.** Every mapped `click`/`fill` carries `extra.strict: true`.
  Why: the non-strict cascade falls through to description matches, so a wrong element
  could be clicked and the version auto-verified. Strict sends a miss to the heal loop
  instead, which is what `sd_heal_test` relies on.
- **Fill values.** BrightSky steps carry no value field; the pilot's value lives in the
  title ("Search for 'The Hobbit'"). Options: take the first single- or double-quoted
  text from the title, then the explanation; or treat every textbox step as unmappable.
  Chosen: the quoted text. Why: the other option fails the pilot's first step forever,
  so the bar's manual check could never exit 0. With no quoted text, the step is
  unmappable.
- **Heal cache off.** Verify runs pass `use_heal_cache=False`, so a verification measures
  the page and does not replay `heal_cache.json`.
- **Queue walk.** The brief decides it: the whole queue, in the order the backend returns
  it (oldest first, `workflows.controller.ts` `verificationQueue`), with no cap. A
  version that fails stays unverified and stays in the queue, so it is re-run on every
  schedule until a human retires it or a heal is promoted.
- **Exit codes.** 0 all passed; 1 any run failed or healed, or a report/propose failed;
  3 bad input or config (env, URL scheme, slug, usage, a 404 on the fetch, and a 401 or
  403 on any guarded call: the token check, the queue read, `POST /runs`,
  `POST /versions`). The fetch is public, so it cannot reveal a bad token; `verify
  <slug>` checks the token first with the cheap guarded queue read, so a bad token exits
  3 before a browser starts instead of surfacing as a failed report (exit 1) after the
  run. Options were that check, or letting the first POST find it. Chosen: the check.
  Rejected: the POST, which wastes a browser run and AI calls and gives the wrong exit
  code. The
  `brightsky` command returns 3 itself instead of raising `CommandError`, which
  `run_cli` maps to 1 for every other command.
- **Proposal retry safety.** The note always contains the run's idempotency key. Before
  the client retries a propose, it re-reads the workflow and treats a version with the
  identical note as success.
- **Token transport.** The token is sent only over `https`, or `http` to a loopback host.
  It is never logged, printed or put in an error message. Loopback requests bypass
  environment proxies (`ProxyHandler({})`); others use the default handler (see map.md
  for the source).
- **Non-current versions.** No backend route returns a non-current version's steps.
  Neither case is run or reported, and a single `verify <slug> --version N` exits 3. What
  a skipped queue entry does to the exit code is the user's choice: ticket 01 (see the
  story "Versions that are not current").

## Interfaces

Environment:
- `BRIGHTSKY_API_URL`: base URL, for example `http://localhost:3001`. A trailing `/` is
  ignored. It is read from the process environment after `load_env()` has loaded `.env`.
- `BRIGHTSKY_BRIDGE_TOKEN`: sent as `Authorization: Bearer <token>`.

CLI (`python3 -m stepper ...`, also `python3 stepper/main.py ...`):
- `brightsky verify <slug> [--version N] [--show]`
- `brightsky verify --all-unverified [--show]`
- Output: one line per workflow,
  `<slug> v<N> passed|failed|healed|skipped[: <reason>][ -> proposed v<M>]`, to stdout.
  Errors go to stderr as `error: <message>`. A CLI test reaches the network and the
  browser only through `stepper.brightsky.verify.make_client` and `make_executor`, so
  monkeypatching those two (or pointing `BRIGHTSKY_API_URL` at a loopback `http.server`
  fake and replacing only `make_executor`) keeps it offline. Exits 0 / 1 / 3 as under Decisions.
  `--version` is parsed and checked by the command itself (a positive integer, else
  exit 3). An option argparse does not recognise is still argparse's usage error, which
  exits 2, as for every other command (`run_cli`'s docstring).

Python (`stepper.brightsky`):
- `config.load_config(environ: Mapping[str, str]) -> BrightSkyConfig` (frozen dataclass:
  `api_url`, `token`). Raises `BrightSkyConfigError` with the messages above.
- `client.Transport`: a Protocol, `send(method, url, headers, body: bytes | None,
  timeout: float) -> HttpResponse`. `HttpResponse` is a dataclass of `status: int` and
  `body: bytes`. A network failure raises `OSError` (including `TimeoutError`).
  `client.UrllibTransport` is the default.
- `client.BrightSkyClient(config, transport=None, sleep=time.sleep)`:
  - `queue() -> tuple[list[QueueItem], list[str]]`: the valid entries in the backend's
    order, and one reason for each malformed entry, which is left out
  - `get_workflow(slug) -> WorkflowDetail`
  - `report_run(slug, report: RunReport) -> None`
  - `propose_version(slug, proposal: Proposal) -> int`, the new version number
  - It raises `BrightSkyHttpError(status, message)` for a 4xx, or for a 5xx after the
    retry, and `BrightSkyResponseError` for a malformed body.
- `models` dataclasses:
  - `QueueItem(slug, version, stepper_runs, created_at)`
  - `WorkflowDetail(slug, site, current_version: int, steps: list[dict], versions:
    list[tuple[int, str | None]])`. The steps are kept as the validated wire dicts, so a
    proposal can copy them unchanged. `versions` holds each version's number and note,
    which the propose retry check reads.
  - `RunStep(step_number, matched, tier, outcome)`
  - `RunReport(version, steps, result, idempotency_key, client="stepper")` with
    `to_json()`
  - `Proposal(steps, source, note)` with `to_json()`
- `mapping.map_version(detail: WorkflowDetail) -> MappedWorkflow`. A `MappedWorkflow`
  holds `steps: list[StepConfig]`, `step_numbers: dict[str, int]` (step description →
  BrightSky step number) and `expectations: dict[str, StepExpectation]`. The function
  raises `UnmappableStep(step_number, reason)`.
- `mapping.url_matches(pathname, expected, mode) -> bool`: bright-sky's `matchUrl`.
- `targets.target_from_element(element: dict, original: dict | None = None) -> dict |
  None`: a stepper element cfg as a BrightSky `PlanStepTarget`, or None when the store
  cannot express it. When `element` has no role+name, only the original target's `role`
  is kept beside the healed selectors, so `map_version` still maps the proposed step to
  the same action (a healed text-entry step stays a `fill`). The old accessibleName is
  dropped, and `map_version` never puts a role without an accessibleName into the
  lookup cfg, so the strict lookup reaches the healed selector.
- `executor.ExecutedStep(step_number, outcome, matched, tier, healed, healed_element,
  error)`. `healed` is true for a step StepRunner reported `healed`; its `outcome` is
  still `failed`.
- `executor.StepExecutor`: a Protocol, `async execute(mapped: MappedWorkflow, *,
  headless: bool) -> list[ExecutedStep]`, one entry per BrightSky step in order.
  - `executor.PipelineExecutor()` is the real one: a headless browser through the
    pipeline.
  - `executor.EngineExecutor(page, resolver, *, ai_service=None, max_heal_attempts=3)`
    runs the mapped steps on a real `StepRunner`, with the real action registry, a real
    `AiHealer` over `ai_service` (a real `AIService()` when None), the
    `ExpectationHook`, a `RecordingResolver` around `resolver`, and no heal cache. It
    launches nothing: `page` is whatever the caller gives (a test double is fine). An
    `ai_service` double needs one method, `async chat(prompt, task_type="classify",
    system="") -> str`, returning a JSON array of one replacement step.
  - The heal loop probes the page through two class methods, which a browser-free test
    monkeypatches: `stepper.engine.healer.dom_snapshot.DOMSnapshotCascade.capture(page,
    step, *, skip_direct=False) -> DomPayload` (an `embed_direct` payload carries
    `healed_cfg`; the strict loop passes `skip_direct=True` after an `embed_direct` miss,
    so a fake should accept the keyword) and
    `stepper.engine.healer.visual_bridge.VisualBridge.check(page, step) -> str | None`.
  - `executor.executed_steps(mapped, results, tiers)` converts StepRunner results; both
    executors use it.
- `verify.verify_slug` and `verify.verify_all_unverified` are `async`.
- `verify.verify_slug(client, executor, slug, *, version=None, headless=True,
  check_token=True) -> VerifyOutcome`. With `check_token`, it calls `client.queue()`
  before the fetch; the queue walk, which has just read the queue, passes False. A
  `BrightSkyHttpError` with status 401 or 403 from any call is never turned into an
  outcome: it propagates (also out of `verify_all_unverified`), and the CLI maps it to
  exit 3. `VerifyOutcome` has `slug`, `version`, `status` (`passed`,
  `failed`, `healed` or `skipped`), `reason` and `proposed_version: int | None`.
- `verify.verify_all_unverified(client, executor, *, headless=True) -> QueueRun`, where
  `QueueRun` has `outcomes: list[VerifyOutcome]`, one per queue entry in queue order.
- `verify.make_executor() -> StepExecutor` and `verify.make_client(config) ->
  BrightSkyClient`: the CLI calls these, and tests monkeypatch them to avoid a browser
  or a network. An acceptance test may instead point `BRIGHTSKY_API_URL` at an
  `http.server` fake on `127.0.0.1`.

Engine changes:
- `HealerStrategy.heal(..., tried: tuple[str, ...] = ())` and a non-abstract
  `HealerStrategy.tier_for(dom, tried) -> str` (default `"healer"`).
  `stepper.engine.healer.interfaces.FREE_TIER = "embed_direct"`.
- `AiHealer.tier_for(dom, tried)`: `"embed_direct"` when `dom.healed_cfg` is set and
  `"embed_direct"` is not in `tried`; else `"big"` when `tried` holds two `"cheap"`;
  else `"cheap"`.
- `StepRunner(..., strict_heal_order: bool = False)` and
  `RunConfig.strict_heal_order: bool = False`, which `build_pipeline` passes on. Only
  when it is true does `StepRunner._run_heal_loop` pass `tried=`, record
  `healed_element["tier"]`, call `capture(..., skip_direct=True)` once `embed_direct` has
  been tried, and leave the first `FREE_TIER` try out of `max_heal_attempts`. When false,
  the loop is unchanged.
- `DOMSnapshotCascade.capture(page, step, *, skip_direct: bool = False)`: with
  `skip_direct=True`, the two `embed_direct` returns become an `embed_candidates`
  payload with JSON `content` and `healed_cfg=None`.
- `StepRunner.add_hook(domain: str | None, hook: StepHook) -> StepRunner`.
- `AIService` gets the task type `heal_big` (chain `["claude_big"]`, max tokens 1024).
  `ClaudeProvider(model=...)` defaults to today's Haiku id.

Wire shapes are bright-sky's DTOs on `claude/workflow-verify`:
`backend/src/workflow-store/api/workflow-store-api.dto.ts` (`ReportRunDto`, `RunStepDto`,
`ProposeVersionDto`, `WorkflowStepDto`), `workflow-store-api.views.ts` (`WorkflowDetail`,
`VerificationQueueItem`, `WorkflowVersionView`) and
`agents/infrastructure/services/element-search/step-target.ts` (`readPlanStepTarget`,
`readExpectedOutcome`).

## Migration and compatibility

Nothing breaks:
- `heal()` gains a keyword with a default, and `tier_for` has a default, so existing
  healers and test doubles keep working. A direct `AiHealer.heal(step, err, dom)` call
  behaves as today.
- The strict heal order is off by default (brief, Decided), so `run --heal N` and CI's
  heal jobs heal exactly as today. `capture`'s new keyword defaults to today's behaviour.
- In BrightSky runs only, `healed_element` gains a `tier` key. The reporters read only
  `healed`.
- The `heal` task chain and every existing CLI command are unchanged.
- The new workflow file does nothing until the secrets are set.

## Risks

- **The schedule never fires, or goes quiet.** GitHub runs `schedule` only from the
  default branch and disables it after 60 days without activity on a public repo
  (map.md has the source). Mitigation: `workflow_dispatch` is there for manual runs, and
  the docs say the file must reach `main`.
- **Open Library's robots.txt disallows `/search` for crawlers.** Mitigation: the pilot
  runs at most once a day and goes through the search form like a person. A different
  pilot site may be needed later (the brief's Unsure line, kept).
- **The pilot's targets may need a heal on the first run.** That run exits 1 and
  proposes v2. The manual check then needs two passing runs of v2 (it is a heal source)
  before it shows verified. This is noted in ticket 09.
- **Catastrophic backtracking from a stored `regex` matchMode.** The pattern comes from a
  write-token holder and is matched against a URL path of at most 2000 characters. The
  scheduled job's `timeout-minutes` bounds a hang.
- **A write-token holder chooses which site the runner visits.** The host guard binds
  navigation to the workflow's own `site`, and no stored value can reach the runner's
  env. But a workflow created for any site makes the scheduled runner browse it in a
  fresh, logged-out context. Mitigation: bridge tokens are issued by the admin. An
  allow-list of sites is a possible later addition and is not built here.
- **AI cost.** There is no queue cap (brief, Decided), so a scheduled run costs at most,
  per queue entry, two cheap calls and one big-model call for each step that heals or
  fails, since the paid attempts are capped at 3. Versions that keep failing stay in the
  queue and are paid for again on every run; the daily schedule and the 30-minute job
  timeout bound it.
