# Map: brightsky-verify

## Destination

`python3 -m stepper brightsky verify <slug>` and `verify --all-unverified` (the whole queue, oldest first) fetch
BrightSky workflow versions with a bridge token, map their steps to strict stepper steps,
and run them headless through the existing pipeline. A step's element that cannot be
found goes through the existing heal cascade in a strict order: a free `embed_direct`
try, then two cheap-tier AI tries, then one big-model try. Each run is reported back with per-step matched, tier and outcome and one
idempotency key. A healed run is reported failed and its healed steps are proposed as a
new unverified version. A daily GitHub Actions workflow runs the queue, and it skips
cleanly while the secrets are unset.

**The bar.**
- `python3 -m pytest stepper/tests/unit/ -q` passes. That includes the new
  `test_brightsky_*.py` files, which prove the mapping for each target kind, a full pass
  with one idempotency key, heal → proposal + failed report, missing env → exit 3, and
  5xx retried once / 4xx not.
- Manually, against a local bright-sky backend on `claude/workflow-verify`,
  `python3 -m stepper brightsky verify openlibrary-find-author` exits 0 and
  `GET /api/workflows/openlibrary-find-author` then shows `currentVersion.status`
  `"verified"`.
- Ticket 09 runs both.

## How to work this

- See what is ready: `python3 scripts/flow-status.py brightsky-verify`. Take the lowest
  numbered READY ticket.
- Claim: set `Status: claimed` in the ticket and save before starting.
- Resolve: write the result under `## Answer`, set `Status: resolved`, then add one line
  to Decisions so far below.
- See the graph: `python3 scripts/flow-status.py brightsky-verify --mermaid` (coloured
  by status, drawn on demand).
- Commands live in `commands.md` (frozen). Lessons live in `learnings.md` (append only).
- Status lives only in the ticket files. This map never repeats it.

## Decisions so far

- Non-current versions (ticket 01, answered by the user 2026-11-01, option A): a non-current queue entry prints `<slug> v<N> skipped: not the current version` and does not change `--all-unverified`'s exit code; `verify <slug> --version N` for a non-current N exits 3.
- 01 — Option A: a non-current `--all-unverified` entry is skipped (`<slug> v<N> skipped: not the current version (v<M>)`), nothing posted, exit code unchanged; `verify <slug> --version N` for a non-current N exits 3.
- 02 — `stepper/brightsky/` config + wire models: `load_config` (https or loopback http only, token hidden from repr/messages), readers raise `BrightSkyResponseError` naming the field (never the value), writers raise `ValueError`; `SLUG_PATTERN` is matched with `fullmatch`.

Outside facts the plan relies on, with their sources:

- GitHub Actions `schedule` runs only on the default branch, can be delayed under load,
  and is disabled automatically in a public repo after 60 days with no repository
  activity (ticket 08, Risks).
  docs: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- `workflow_dispatch` triggers only when the workflow file exists on the default branch
  (ticket 08). docs: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Secrets cannot be referenced directly in `if:` conditionals; the documented pattern is
  to map them to a job-level `env` and test that in step conditions. Secrets are not
  passed to workflows triggered from forks (ticket 08).
  docs: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- Workflow syntax facts ticket 08 and spec.md § Risks rely on (none of these keys is in
  `ci.yml` today). docs: https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions
  - `concurrency`: "there can be at most one running job or workflow in a concurrency
    group at any time"; without `cancel-in-progress`, a newly queued run replaces a
    pending one, so two scheduled runs never overlap.
  - `permissions`: sets what `GITHUB_TOKEN` may do; once any permission is given, every
    unspecified one is set to none, so `permissions: contents: read` leaves the token
    able only to read the repository.
  - `jobs.<job_id>.timeout-minutes`: "The maximum number of minutes to let a job run
    before GitHub automatically cancels it", default 360. The workflow sets 30, which
    bounds a hung regex match or a long AI-heal run.
- Open Library's `User-agent: *` group has `Disallow: /search` (spec Risks; the pilot
  runs at most daily through the form). docs: https://openlibrary.org/robots.txt
- `urllib.request.ProxyHandler`, by default, reads proxies from the `<protocol>_proxy`
  environment variables, and `ProxyHandler({})` disables the autodetected proxy. This is
  why the client builds a no-proxy opener for loopback hosts and needs no `NO_PROXY` for
  a local backend (ticket 02).
  docs: https://docs.python.org/3/library/urllib.request.html (ProxyHandler); checked
  against `/usr/lib/python3.13/urllib/request.py` (`proxy_bypass_environment`) on this
  host.
- YAML 1.1 resolves the plain scalar `on` to boolean true, so PyYAML's `safe_load` of a
  workflow file returns the `on:` block under the key `True` (ticket 08's test reads
  `data.get("on", data.get(True))`). docs: https://yaml.org/type/bool.html; checked on
  this host with PyYAML 6.0.3: `yaml.safe_load("on:\n  schedule: []\n")` →
  `{True: {'schedule': []}}`.

- GitHub Actions' `notice` workflow command is `::notice file={name},line={line},endLine={endLine},title={title}::{message}`,
  every parameter is optional, and a bash `run:` step emits it with `echo` (ticket 08's
  skip step echoes `::notice title=BrightSky verification skipped::...`, and its test
  asserts `::notice` in that script).
  docs: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands
- Playwright's `Locator.input_value(*, timeout=None) -> str` returns the value of the
  matching `<input>`, `<textarea>` or `<select>` (or of the control a `<label>` is
  associated with) and throws for any other element; it was added in v1.14, and the
  pinned version is 1.56.0 (`requirements.txt`). Ticket 05's `value_set` check uses it,
  and a throw counts as "not met".
  docs: https://playwright.dev/python/docs/api/class-locator (`input_value`); checked on
  this host: `inspect.signature(playwright.async_api.Locator.input_value)` →
  `(self, *, timeout: Optional[float] = None) -> str` with playwright 1.56.0.
- `claude-sonnet-4-20250514` was retired on 2026-06-15, and requests to retired models
  fail. Its listed replacement, `claude-sonnet-5-5`, is active. So the big-model rung
  uses `claude-sonnet-5-5` (ticket 04).
  docs: https://platform.claude.com/docs/en/about-claude/model-deprecations

Facts read from the bright-sky checkout (`/home/claude/bright-sky`, branch
`claude/workflow-verify`, HEAD 3538079, read only):

- `GET /api/workflows/:idOrSlug` is public and returns `currentVersion` (no steps),
  `currentSteps` and `versions` (no steps). The current version is the highest verified,
  else the highest unverified. No route returns a non-current version's steps
  (`workflows.controller.ts`, `workflow-store.service.ts` `currentVersion`).
- `GET verification-queue`, `POST :idOrSlug/runs` and `POST :idOrSlug/versions` need
  `Authorization: Bearer <token>` (`bridge/workflow-access.guard.ts`), and are throttled
  at 100 requests a minute (`app.module.ts`).
- `ReportRunDto`: `version` int ≥ 1; `steps` ≤ 50 with unique `stepNumber`, each with
  `matched` bool, `tier` string ≤ 100 or null, and `outcome` `passed|failed|unchecked`;
  `result` `passed|failed|incomplete`; `client?`; `idempotencyKey?` 1–100 characters.
  A bridge token's client overrides the body's.
- `ProposeVersionDto`: `steps` 1–50 of `WorkflowStepDto` (`title` ≤ 200, `explanation`
  ≤ 2000, `expectedDomain?`, `expectedUrl?`, `matchMode?` `startsWith|includes|regex`,
  `target?`, `expectedOutcome?`); `source` `claude|haiku|human|stepper`; `note?` ≤ 1000.
- A target needs `selectors` (≤ 5 strings), `score` 0..1, `grounding`
  `current_page|future_page|break_point`, and either a non-blank role plus
  accessibleName or at least one selector (`readPlanStepTarget`). Outcome kinds:
  `value_set`, `element_gone` and `element_appears` (each with a target), and
  `url_change` (`urlContains?`).
- `matchUrl` compares the page's pathname. The default mode is `startsWith`, and a regex
  that does not compile falls back to `startsWith`
  (`workflow-scenarios/url-match.utils.ts`).
- Auto-promotion: a stepper run that is a full pass (steps 1..n, all `passed`) promotes
  an unverified version. Versions with source `stepper` or `haiku` need two such runs
  with distinct idempotency keys; other sources need one
  (`workflow-verification.service.ts`).

- `GET /api/workflows/verification-queue` returns unverified versions oldest first
  (`workflows.controller.ts` `verificationQueue` docstring). The brief's Decided line:
  walk all of it in that order, no cap.
- `AIService.chat` falls back to the `classify` chain for a task type it does not know
  (`_TASK_CHAINS.get(task_type, _TASK_CHAINS["classify"])` in
  `stepper/engine/ai/service.py`), so the `heal_big` chain (ticket 04) must exist before
  AiHealer asks for it (ticket 12).
- Today `AiHealer.heal` returns `dom.healed_cfg` with no AI call whenever it is set, on
  every attempt, so an `embed_direct` cfg that misses never reaches the AI. Both
  `embed_direct` returns in `DOMSnapshotCascade.capture` carry `content=""`, and the heal
  loop captures again on every attempt, so an AI rung after a miss would see no page
  (`stepper/engine/healer/dom_snapshot.py`). The brief's Decided lines: `capture` gets an
  opt-in `skip_direct` (ticket 14), and the strict order is opt-in, BrightSky only
  (ticket 12); CI's keyless heal job (`sd_heal_test`, `sd_full_heal_flow` with
  `--heal 2`, `.github/workflows/ci.yml`) keeps today's behaviour.

Ticket lines are added here as tickets resolve.

## Open questions

- user: (ticket 01) No backend route returns a non-current version's steps, so stepper
  never runs one: `verify <slug> --version N` for a non-current N exits 3, and such a
  queue entry is printed `skipped` with nothing posted. Should a skipped queue entry
  leave the queue walk's exit code alone (A, recommended: the schedule stays green), or
  make it 1 (B: the schedule shows red until the backend serves named versions)?
- Not settled by the code: whether the pilot's role/name targets match Open Library's
  live page. The first manual run (ticket 09) will show it, and a heal there is expected
  and useful.
