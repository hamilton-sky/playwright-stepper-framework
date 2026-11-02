# Add the scheduled GitHub Actions workflow that walks the verification queue

Type: task
Status: resolved
Blocked by: —
Test first: yes
Level: 3
Floor: allow config
Touches: .github/workflows/brightsky-verify.yml, stepper/tests/unit/test_brightsky_workflow_file.py

The brief asks for a new CI workflow file, so this ticket may add CI config
(`Floor: allow config`). Level 3, because it handles the bridge token and AI keys as
repo secrets.

`.github/workflows/brightsky-verify.yml` (new):
- **Triggers.** `on:` holds `schedule` (one daily cron, for example `"17 6 * * *"`; the
  pilot runs at most once a day, spec Risks) and `workflow_dispatch`.
- **Job settings.** `permissions: contents: read`, a `concurrency` group so two runs
  never overlap, `timeout-minutes: 30`, and `runs-on: ubuntu-latest`.
- **Job-level `env`:**
  - `BRIGHTSKY_API_URL: ${{ secrets.BRIGHTSKY_API_URL }}`;
  - `BRIGHTSKY_BRIDGE_TOKEN: ${{ secrets.BRIGHTSKY_BRIDGE_TOKEN }}`;
  - the optional `GROQ_API_KEY`, `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` from secrets,
    as `ci.yml`'s integration job does.
  - Secrets cannot be tested in `if:` directly, so they go through env (map.md has the
    docs line).
- **First step, `id: secrets`.** A shell test of the two env vars. When both are set, it
  writes `available=true` to `$GITHUB_OUTPUT`. Otherwise it writes `available=false` and
  echoes `::notice title=BrightSky verification skipped::BRIGHTSKY_API_URL /
  BRIGHTSKY_BRIDGE_TOKEN are not set ...` (the `notice` workflow command; map.md has
  the docs line), plus a line to `$GITHUB_STEP_SUMMARY`. It
  exits 0 either way. It reads the env, never `${{ secrets.* }}` inside `run:`, the same
  as `ci.yml`'s "Detect OpenLibrary credentials".
- **Every later step** has `if: steps.secrets.outputs.available == 'true'`:
  - checkout;
  - setup-python 3.11;
  - the pip cache;
  - `pip install -r requirements.txt` and `pip install -e .`;
  - `playwright install chromium --with-deps`;
  - the model cache and `python stepper/download_models.py`;
  - `python -m stepper brightsky verify --all-unverified`. It runs headless by default.
  - These copy `ci.yml`'s steps.
- A comment at the top says the schedule fires only once this file is on the default
  branch, and that a public repo disables it after 60 days without activity (map.md
  docs line).

`stepper/tests/unit/test_brightsky_workflow_file.py` (new) loads the file with
`yaml.safe_load`. PyYAML reads the `on` key as `True`, so it uses
`data.get("on", data.get(True))` (map.md docs line). It asserts:
- the `schedule` and `workflow_dispatch` triggers;
- the job env maps both BrightSky secrets;
- the first step has `id: secrets` and its script contains `::notice`;
- every later step's `if` names `steps.secrets.outputs.available`;
- some step's `run` contains `brightsky verify --all-unverified`;
- no `run` string contains `secrets.`;
- `permissions == {"contents": "read"}`, and a `timeout-minutes` is set.

## Not in this ticket

- Changes to `.github/workflows/ci.yml`. The unit job there already runs the new test
  files.
- Setting the secrets, which the owner does once the backend has a deployment (the
  brief's Unsure line, kept).

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_workflow_file.py -q` passes, with
  every assertion above.
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/brightsky-verify.yml'))"`
  exits 0.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_workflow_file.py -q
prints passed
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/brightsky-verify.yml')); print('yaml ok')"
prints yaml ok
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Stories ("Run on a schedule"), § Risks
- map.md § Decisions so far (GitHub Actions `schedule`, secrets, `::notice`,
  `concurrency`, `permissions` and `timeout-minutes` docs lines; the PyYAML `on` key)
- `.github/workflows/ci.yml` (the integration job's install steps and its "Detect
  OpenLibrary credentials" step)

## Answer


Work started at commit `6973a09b0e00f6892beeb456640644df1f62e58a`; the test-only commit is `test(brightsky-verify): 08 failing test` (7 failed: the workflow file did not exist).

**Built**
- `.github/workflows/brightsky-verify.yml` (new): `on: schedule` (`"17 6 * * *"`) + `workflow_dispatch`; one job `verify` with `runs-on: ubuntu-latest`, `timeout-minutes: 30`, `permissions: contents: read`, `concurrency: group: brightsky-verify`; job env maps `BRIGHTSKY_API_URL`, `BRIGHTSKY_BRIDGE_TOKEN`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` from secrets. First step `id: secrets` tests the env, writes `available=true|false`, and on false echoes `::notice title=BrightSky verification skipped::...` naming both secrets plus a `$GITHUB_STEP_SUMMARY` line; no exit. Every later step (checkout, setup-python 3.11, pip cache, both installs, playwright, model cache, model download, `python -m stepper brightsky verify --all-unverified`) has `if: steps.secrets.outputs.available == 'true'`. Header comment covers default-branch-only and the 60-day public-repo disable.
- `stepper/tests/unit/test_brightsky_workflow_file.py` (new): 7 tests covering every assertion the ticket lists (triggers, job env secrets, first step id + `::notice`, gating of every later step, the verify run, no `secrets.` in any `run`, permissions/timeout, plus concurrency present).

**Proof**
- `python3 -m pytest stepper/tests/unit/test_brightsky_workflow_file.py -q` → `7 passed in 0.06s`, exit 0.
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/brightsky-verify.yml')); print('yaml ok')"` → `yaml ok`, exit 0.
- `python3 -m pytest stepper/tests/unit/ -q` → `1884 passed in 19.07s`, exit 0.
- Also: `python3 -m pytest plans/brightsky-verify/acceptance/test_accept_schedule.py -q` → `3 passed`; Build `compileall` exit 0; Lint `validate` exit 0.

**Decisions**
- `concurrency` without `cancel-in-progress`, so a running verify is never cut mid-report (map.md docs line: a new queued run replaces a pending one).
- `permissions`, `timeout-minutes` and `concurrency` sit at job level (the test accepts workflow level too for permissions/concurrency).
- Step summary is one line rather than ci.yml's multi-line block: the ticket asks for "a line".

**Shortcuts taken**: none.

**For later tickets**
- The verify step fails when run until ticket 07 adds `brightsky verify` to the CLI; with secrets unset (today) it is skipped, so the job is green.
- Ticket 07's docs could mention this workflow and the two secrets; this ticket did not touch README.
