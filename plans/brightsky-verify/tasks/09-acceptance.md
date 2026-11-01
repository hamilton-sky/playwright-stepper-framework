# Run the bar end to end

Type: task
Status: open
Blocked by: 02, 03, 04, 05, 06, 07, 08, 10, 11, 12, 13, 14, 15
Test first: no
Level: 1

Prove the map's bar. Change no code. If something fails, write it under `## Answer`
with the output, and stop. The fix belongs in the ticket that owns that file.

1. **Unit bar.** `python3 -m pytest stepper/tests/unit/ -q` passes. Then confirm that
   each bar item has a named test, and list the file and test name for each in the
   Answer:
   - mapping per target kind: `test_brightsky_mapping.py`;
   - a full pass with one idempotency key: `test_brightsky_verify.py`;
   - missing element → heal (in the brief's order) → proposal (source and note) +
     failed report: `test_brightsky_heal_loop.py`;
   - missing env → exit 3: `test_brightsky_cli.py`;
   - 5xx retried once, 4xx not: `test_brightsky_client.py`.
2. **Manual check.** This needs a running bright-sky backend, a bridge token, a browser
   and the network.
   - Start bright-sky's backend from `/home/claude/bright-sky` on branch
     `claude/workflow-verify` (`docker-compose up`, or `cd backend && npm run start:dev`
     with PostgreSQL). Issue a bridge token for client `stepper` through
     `POST /api/bridge-tokens` as admin. learnings.md's (09) line lists what the backend
     needs to boot on this host and how to mint the admin JWT.
   - Export `BRIGHTSKY_API_URL=http://localhost:3001` and `BRIGHTSKY_BRIDGE_TOKEN`.
   - On a host whose prebuilt chromium differs from the pinned Playwright's, also export
     `BROWSER_EXECUTABLE_PATH` (CLAUDE.md, "Run against a browser Playwright did not
     download for itself").
   - Run `python3 -m stepper brightsky verify openlibrary-find-author`. It must exit 0,
     and `GET /api/workflows/openlibrary-find-author` must then show
     `data.currentVersion.status` `"verified"` (the backend wraps every success body in
     `{"success", "data", "timestamp"}`; ticket 15).
   - If the first run heals instead (exit 1, `-> proposed v2`), that is the loop working
     (the brief's Unsure line). v2 is now current, and with source `stepper`/`haiku` it
     needs two passing runs with distinct keys. Run the command twice more. The second of
     those must exit 0, and the status must then read `"verified"`. Record every run's
     output in the Answer.
3. **Schedule.** Confirm in the Answer that `.github/workflows/brightsky-verify.yml` (new, from ticket 08)
   exists and that its test passed in step 1. It cannot fire until the file reaches
   `main` and the secrets are set.

## Not in this ticket

- Setting the repo secrets or merging to `main`; the owner does those.
- Fixing anything found. Each fix goes back to the ticket that owns the file.

## Done when

- `python3 -m pytest stepper/tests/unit/ -q` passes, and the Answer names the test for
  each of the five bar items.
- `python3 -m stepper brightsky verify openlibrary-find-author` exits 0 against the
  local backend. The Answer says how many runs that took.
- Fetching `$BRIGHTSKY_API_URL/api/workflows/openlibrary-find-author` then shows
  `"status":"verified"` at `data.currentVersion.status`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
$ python3 -m stepper brightsky verify openlibrary-find-author
prints openlibrary-find-author
needs a local bright-sky backend on claude/workflow-verify, BRIGHTSKY_API_URL and BRIGHTSKY_BRIDGE_TOKEN set, a chromium browser and network access to openlibrary.org
$ python3 -c "import json, os, urllib.request as u; o = u.build_opener(u.ProxyHandler({})); d = json.load(o.open(os.environ['BRIGHTSKY_API_URL'].rstrip('/') + '/api/workflows/openlibrary-find-author')); print('status:' + d['data']['currentVersion']['status'])"
prints status:verified
needs a local bright-sky backend on claude/workflow-verify with BRIGHTSKY_API_URL set, after a passing verify run
```

## Reference

- map.md § Destination (the bar)
- spec.md § Goal and the bar, § Risks
- `/home/claude/bright-sky/backend/src/workflow-store/pilot-workflows.ts` (read only)

## Answer


Not resolved: the manual bar fails. Work started at `03ff4826d86dfd4de1d37e48d0d3805b55c417d1`; no code changed.

**Step 1, unit bar: passes.** `python3 -m pytest stepper/tests/unit/ -q` printed `2162 passed in 38.91s`, exit 0. The test for each bar item:
- mapping per target kind: `stepper/tests/unit/test_brightsky_mapping.py::test_target_kinds` (parametrised over the kinds), plus `test_the_pilot_maps_to_navigate_fill_click_click`;
- full pass with one idempotency key: `test_brightsky_verify.py::test_a_full_pass_posts_one_passed_report_with_one_key_and_no_proposal` (and `test_each_run_gets_its_own_idempotency_key`);
- missing element, then heal in the brief's order, then proposal (source and note) and a failed report: `test_brightsky_heal_loop.py::test_an_embed_direct_heal_is_reported_failed_then_proposed_from_stepper` and `test_a_missed_embed_direct_then_two_cheap_misses_heal_on_the_big_model`;
- missing env exits 3: `test_brightsky_cli.py::test_a_missing_variable_exits_3_with_no_traceback_and_no_client`;
- 5xx retried once, 4xx not: `test_brightsky_client.py::test_a_503_then_a_200_makes_two_calls_with_one_recorded_sleep`, `test_two_503s_raise_brightsky_http_error_503_after_two_calls`, `test_a_4xx_raises_after_exactly_one_call_with_no_sleep`.

**Step 3, schedule.** `.github/workflows/brightsky-verify.yml` exists, and its test `stepper/tests/unit/test_brightsky_workflow_file.py` is part of the 2162 that passed.

**Step 2, manual check: fails on run 1.** Setup: bright-sky `/home/claude/bright-sky` on `claude/workflow-verify` (HEAD 3538079), shared and backend built (`nest build` needed `NODE_OPTIONS=--max-old-space-size=6144`; the default heap aborted), started with `node dist/backend/src/main` against the host's PostgreSQL 16 cluster (db `brightsky`) and a local redis-server. Env: a random `JWT_SECRET`, `NODE_ENV=development`, `DB_*`, and placeholder `GOOGLE_CLIENT_ID/SECRET/CALLBACK_URL` (the backend refuses to boot without them). Admin: a locally signed JWT with `role: admin`. `POST /api/bridge-tokens {"client":"stepper"}` returned 201 with a token. The pilot `openlibrary-find-author` v1 is seeded, `unverified`. Exported `BRIGHTSKY_API_URL=http://localhost:3001`, `BRIGHTSKY_BRIDGE_TOKEN`, `BROWSER_EXECUTABLE_PATH=/opt/pw-browsers/chromium`.

Run 1, `python3 -m stepper brightsky verify openlibrary-find-author`, exit 1:
```
15:36:26 | INFO | stepper.brightsky.client | brightsky request method=GET path=/api/workflows/verification-queue status=200 attempt=1 duration_ms=18
error: the verification queue must be a list
```
(The token does not appear in the output.)

Cause: the backend's global `TransformInterceptor` (`/home/claude/bright-sky/backend/src/main.ts`, `/home/claude/bright-sky/backend/src/common/interceptors/transform.interceptor.ts`) wraps every response not marked `@SkipTransform()` as `{"success": true, "data": <body>, "timestamp": ...}`. No workflow-store controller is marked, so the queue, the workflow detail, the run report and the propose responses are all enveloped. `stepper/brightsky/client.py` (line 151, `queue must be a list`) and the readers in `models.py` parse the bare body. What the backend actually returned:
- `GET /api/workflows/verification-queue` → `dict ['data', 'success', 'timestamp']`, `data` a list of 1: `('openlibrary-find-author', 1)`;
- `GET /api/workflows/openlibrary-find-author` → `data.currentVersion.status` = `unverified`.

The ticket's own third check command reads `d['currentVersion']` and fails the same way against this backend: `KeyError: 'currentVersion'`. It would have to read `d['data']['currentVersion']['status']`.

Runs needed for exit 0: not reached (one run, failed before anything ran).

**Shortcuts taken**: none.

**For later tickets**
- Ticket 10 (`client.py`, maybe `models.py` too) has to unwrap the `{"success", "data", "timestamp"}` envelope on every response. That includes the error bodies, if the interceptor's exception filter wraps them too; check `message` handling. The other option is a backend change (`@SkipTransform()` on the workflow-store controllers), but bright-sky is read-only to this plan. map.md's "Facts read from the bright-sky checkout" left out the envelope, and the offline tests' stub transport returns bare bodies, so the unit bar could not catch this.
- This ticket's check block (status command) needs `d['data']['currentVersion']['status']`. That is ticket text above the Answer, so a human has to change it.
- The backend is still running locally on :3001 (PostgreSQL 16 cluster `main` and a daemonised redis-server started for it), so a rerun can reuse it.

## Attempt note

Attempt 1 (auto): the unit bar passes (2162) and step 3 is confirmed. The manual run exits 1 with `error: the verification queue must be a list`: the bright-sky backend wraps every response in `{"success":true,"data":...,"timestamp":...}` (global TransformInterceptor) and the stepper client parses the bare body. Fixing it needs `stepper/brightsky/client.py` (ticket 10's file), and probably the ticket 09 check command's `d['currentVersion']` changed to `d['data']['currentVersion']`. Both are outside this ticket, which changes no code. Options: reopen ticket 10 with a review finding to unwrap the envelope, or add a new ticket for it and block 09 on it. Then run 09 again.
