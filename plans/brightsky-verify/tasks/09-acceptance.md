# Run the bar end to end

Type: task
Status: open
Blocked by: 02, 03, 04, 05, 06, 07, 08, 10, 11, 12, 13, 14
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
     `POST /api/bridge-tokens` as admin.
   - Export `BRIGHTSKY_API_URL=http://localhost:3001` and `BRIGHTSKY_BRIDGE_TOKEN`.
   - On a host whose prebuilt chromium differs from the pinned Playwright's, also export
     `BROWSER_EXECUTABLE_PATH` (CLAUDE.md, "Run against a browser Playwright did not
     download for itself").
   - Run `python3 -m stepper brightsky verify openlibrary-find-author`. It must exit 0,
     and `GET /api/workflows/openlibrary-find-author` must then show
     `currentVersion.status` `"verified"`.
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
- Fetching `$BRIGHTSKY_API_URL/api/workflows/openlibrary-find-author` then prints
  `"status":"verified"` for the current version.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
$ python3 -m stepper brightsky verify openlibrary-find-author
prints openlibrary-find-author
needs a local bright-sky backend on claude/workflow-verify, BRIGHTSKY_API_URL and BRIGHTSKY_BRIDGE_TOKEN set, a chromium browser and network access to openlibrary.org
$ python3 -c "import json, os, urllib.request as u; o = u.build_opener(u.ProxyHandler({})); d = json.load(o.open(os.environ['BRIGHTSKY_API_URL'].rstrip('/') + '/api/workflows/openlibrary-find-author')); print('status:' + d['currentVersion']['status'])"
prints status:verified
needs a local bright-sky backend on claude/workflow-verify with BRIGHTSKY_API_URL set, after a passing verify run
```

## Reference

- map.md § Destination (the bar)
- spec.md § Goal and the bar, § Risks
- `/home/claude/bright-sky/backend/src/workflow-store/pilot-workflows.ts` (read only)

## Answer

