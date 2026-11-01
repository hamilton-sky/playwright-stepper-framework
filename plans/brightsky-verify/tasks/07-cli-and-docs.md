# Add the `brightsky verify` command and document the adapter

Type: task
Status: resolved
Blocked by: 01, 06
Test first: yes
Level: 3
Touches: stepper/cli.py, stepper/tests/unit/test_brightsky_cli.py, README.md, ARCHITECTURE.md

Level 3: the command builds the config from `os.environ`, which holds
`BRIGHTSKY_BRIDGE_TOKEN`; it prints client errors to stderr, which the scheduled job
writes to its CI logs; and its exit codes decide whether the schedule goes red. Every
message it prints comes from the exception's text or the outcome's reason, never from
the config or the environment.

**`stepper/cli.py`**
- Add `"brightsky"` to `_COMMANDS`, so `normalize_argv` passes it through.
- In `build_parser()`, after the `heal` block, add a `brightsky` parser with a `verify`
  subparser:
  - positional `slug` (`nargs="?"`);
  - `--all-unverified`;
  - `--version` (`metavar N`, kept as a string and checked by the command);
  - `--show`;
  - `set_defaults(func=cmd_brightsky_verify, quiet=False)`.
  - `brightsky` with no subcommand prints its help and returns 0, the way `heal` does.
  - Add the two forms to `_EPILOG`.
- `cmd_brightsky_verify(args, pipeline)` imports `stepper.brightsky` lazily and returns
  the exit code itself.
  - Usage problems print `error: ...` to stderr and return 3:
    - both a slug and `--all-unverified`, or neither;
    - `--version` together with `--all-unverified`;
    - `--version` that is not a positive integer.
  - `BrightSkyConfigError` → `error: <message>`, 3.
  - `BrightSkyHttpError` with status 401 or 403, from any call (the token check, the
    queue read, `POST /runs`, `POST /versions`; ticket 06 lets these propagate):
    `error: bridge token rejected (HTTP <status>): <backend message>`, 3. A 404 on the
    fetch: `error: ...`, 3. Any other `BrightSkyHttpError`: 1.
  - `BrightSkyResponseError` → 1.
  - Otherwise it calls `asyncio.run(verify_slug(...))` or
    `asyncio.run(verify_all_unverified(...))` with `make_client(load_config(os.environ))`
    and `make_executor()`, and `headless=not args.show`.
  - It prints through `_out` one line per outcome, in queue order,
    `<slug> v<N> <status>[: <reason>][ -> proposed v<M>]`.
- Exit codes: 0 when every outcome passed (or the queue was empty), 1 when any failed or
  healed. A `skipped` outcome from a single `verify <slug> --version N` prints
  `error: <slug> v<N> is not the current version (v<M>); the backend serves only the
  current version's steps` to stderr and returns 3, under either answer to ticket 01. In
  the queue walk a `skipped` line is printed, and its effect on the exit code is ticket
  01's Answer: none under A, 1 under B.
- `run_cli` is unchanged. It has already called `pipeline.load_env()`, so a `.env` with
  the two variables works.

**Docs**
- README.md: a "BrightSky verification" section after "Self-Healing — DOM Snapshot
  Cascade". It covers:
  - the two variables and the https/loopback rule;
  - the two commands and their exit codes;
  - healed = failed + proposal, with source `stepper`/`haiku`;
  - the heal order (a free `embed_direct` try, two cheap-tier tries, then the big model)
    and the key the big model needs;
  - that `--all-unverified` walks the whole queue, oldest first, with no cap, and what
    that means for AI cost (spec.md § Risks);
  - the scheduled workflow, its secrets, and that it must reach `main` to run.
- ARCHITECTURE.md: a matching short section after "Self-healing cascade", with the spec's
  Design diagram.
- Keep both short. Facts come from spec.md.

## Not in this ticket

- The scheduled workflow file (ticket 08).
- `docs/statuses-and-exit-codes.md`. It documents `run`'s statuses, and the brief asks
  only for a README/ARCHITECTURE section.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_cli.py -q` passes. It drives
  `cli.run_cli` with a stub pipeline (`load_env`, `_stepper_root`) and monkeypatched
  `make_client` / `make_executor`, and its tests show:
  - missing `BRIGHTSKY_API_URL` returns 3 with `error: BRIGHTSKY_API_URL is not set` on
    stderr, no traceback, and no client built; the same for the token;
  - with `BRIGHTSKY_BRIDGE_TOKEN=tok-SECRET-123`, none of the stdout or stderr from a
    config error (http to a non-loopback host), a 401, a 503 after the retry, or a
    malformed response contains `tok-SECRET-123`;
  - both a slug and `--all-unverified` return 3, and so does neither;
  - `--version x` returns 3;
  - a 404 on the fetch returns 3, and a 503 returns 1;
  - with a stubbed transport (through `make_client`) answering 401 to
    `GET /api/workflows/verification-queue`, `verify openlibrary-find-author` returns 3,
    prints `bridge token rejected (HTTP 401)` to stderr, sends exactly one request, and
    `make_executor` is never called; a 403 on `POST /runs` returns 3 with the same error,
    and a 401 on `POST /versions` returns 3;
  - a passed outcome returns 0 and prints `openlibrary-find-author v1 passed`;
  - a healed one returns 1 and prints `-> proposed v2`;
  - an empty queue returns 0, and a queue of a passed and a failed entry prints both
    lines in queue order and returns 1;
  - `--version 2` when the fetch's current version is 1 returns 3 with the
    not-current error, and a queue holding only a non-current entry prints `skipped`
    and returns the exit code ticket 01's Answer names.
- `python3 -m pytest stepper/tests/unit/test_cli.py -q` passes unchanged.
- `python3 -m stepper brightsky verify --help` prints `--all-unverified`.
- README.md has a `BrightSky verification` heading and ARCHITECTURE.md has a matching BrightSky section: `grep -c "BrightSky verification" README.md` prints at least 1, and `grep -ci "brightsky" ARCHITECTURE.md` prints at least 1.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_cli.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_cli.py -q
prints passed
$ python3 -m stepper brightsky verify --help
prints --all-unverified
$ grep -q "BrightSky verification" README.md
$ grep -qi "brightsky" ARCHITECTURE.md
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Stories, § Interfaces (CLI), § Decisions ("Exit codes")
- tasks/01 Answer
- `stepper/cli.py` `build_parser` (the `heal` block), `cmd_run`, `run_cli`, `_out`
- `stepper/tests/unit/test_cli.py` for how `run_cli` is driven with a stub pipeline

## Answer


Work started at commit `d183fc04fe99376e4878fcc41f72d9c9de6da553`. The failing-test commit is `11ef5ef`. It failed with argparse `invalid choice: 'brightsky'`.

**Built**
- `stepper/cli.py`:
  - `"brightsky"` added to `_COMMANDS`, plus a docstring line.
  - The `brightsky` parser with a `verify` subparser: `slug` (`nargs="?"`), `--all-unverified`, `--version N` (a string) and `--show`. `brightsky` with no subcommand prints its help and returns 0.
  - Two `_EPILOG` lines.
  - `cmd_brightsky_verify` and its helpers `_err`, `_outcome_line`, `_LazyExecutor` and `_BRIGHTSKY_BAD_INPUT = 3`.
- `stepper/tests/unit/test_brightsky_cli.py` (new, 31 tests). It drives `cli.run_cli` with a stub pipeline, `verify.make_client` wrapping a recording `StubTransport`, and `verify.make_executor` giving a scripted `FakeExecutor`.
- `README.md`: a "BrightSky verification" section after "Self-Healing — DOM Snapshot Cascade". It covers the variables and the https/loopback rule, both commands, exit codes, healed = failed + proposal (`stepper`/`haiku`), the heal order and `ANTHROPIC_API_KEY`, the no-cap cost, and the schedule (its secrets, must be on `main`, the 60-day disable).
- `ARCHITECTURE.md`: a TOC entry and a "BrightSky verification" section after "Self-healing cascade". It holds the spec's Design diagram and four short decisions.

**Proof** (each run fresh, after the last edit)
- `python3 -m pytest stepper/tests/unit/test_brightsky_cli.py -q`: `31 passed`. The tests cover:
  - a missing `BRIGHTSKY_API_URL` or token: exit 3, `error: <NAME> is not set`, no traceback, `clients == 0`, no request;
  - the token `tok-SECRET-123` is absent from stdout and stderr for the http-non-loopback config error, a 401 on the token check, a 401 on the queue read, a 503 after the retry (the fetch sent twice), a 503 on the queue read, and a malformed detail (exit 1, names `currentVersion`);
  - both a slug and `--all-unverified`, and neither: 3. `--version` = `x`, `0`, `-1` or `1.5`: 3. `--version` with `--all-unverified`: 3. A bad slug: 3. None of these sends a request;
  - a 404 on the fetch: 3 (`error: HTTP 404: Workflow not found`). A 503: 1;
  - a 401 on `GET verification-queue`: 3, `bridge token rejected (HTTP 401): Invalid bridge token`, `calls() == [GET queue]`, `make_executor` called 0 times. A 403 on `POST /runs`: 3, one POST. A 401 on `POST /versions`: 3, one POST;
  - passed: 0 and `openlibrary-find-author v1 passed`. Healed: 1 and `... v1 healed -> proposed v2`. Failed: 1 with its reason. `--show` gives `headless=False`;
  - an empty queue: 0. A passed entry then a failed one: both lines in queue order, 1. A malformed entry prints `? failed: entry 1: ...`;
  - `--version 2` when current is 1: 3, the not-current error, only `[GET queue, GET detail]`, nothing on stdout. A queue of only a non-current entry prints `old-flow v1 skipped: not the current version (v2)` and gives 0 (ticket 01, option A).
- `python3 -m pytest stepper/tests/unit/test_cli.py -q`: `49 passed`. The file is unchanged.
- `python3 -m stepper brightsky verify --help`: exit 0, and the output lists `--all-unverified`.
- `grep -c "BrightSky verification" README.md` gives `1`, and `grep -ci "brightsky" ARCHITECTURE.md` gives `8`.
- `python3 -m pytest stepper/tests/unit/ -q`: `2162 passed`.
- Also checked:
  - Build (`compileall`) and Lint (`stepper/main.py validate`) both exit 0.
  - Acceptance (`plans/brightsky-verify/acceptance`) gives `161 passed`, up from 57 failing after ticket 06. That includes `test_missing_env_exits_3_from_the_real_entry_point` through `python3 -m stepper`.

**Decisions**
- **The slug is checked against `SLUG_PATTERN` before the config or any request**, giving 3 with `error: the slug must match ...`. The ticket's usage list does not name this, but spec.md's story and the acceptance test `test_a_malformed_slug_exits_3` require it. Without the check, the token check would go out first and the client's `ValueError` would surface as a traceback.
- **A 404 maps to 3 wherever it comes from.** In single mode it can come from the token check or the fetch. In the walk, only the queue read can raise it, because entry errors become outcomes. A 404 on the guarded queue read means the URL points at the wrong place, which is a config error.
- **`make_executor` is called lazily**, on the first `execute`, through `_LazyExecutor`, and only once per command. This is how a rejected token builds no executor, as Done when asks. `make_client(load_config(os.environ))` is called as the ticket says.
- **A non-current `--version` prints its message to stderr only.** The message is built from the outcome's reason: `<slug> v<N> is not the current version (v<M>); the backend serves only the current version's steps`. No stdout line is printed.
- **An outcome with `version=None`** (a rejected queue entry) prints as `? failed: <reason>`, with no `v`.
- **Error messages come from `str(exc)` / `exc.message` / `outcome.reason`.** The client and config already scrub the token from these. Nothing reads the config or the environment for output.

**Shortcuts taken**
- An exception other than the client's two (a browser crash or `DomainNotReadyError` from the executor) is not caught by `cmd_brightsky_verify`. `run_cli` catches `DomainNotReadyError` and returns 1, and anything else is a traceback. The same gap is noted in 06's Answer. It is worth handling once real runs show it.

**For later tickets**
- 09: `python3 -m stepper brightsky verify openlibrary-find-author` is wired. The command loads `.env` through `run_cli`'s `pipeline.load_env()`. It logs INFO, including one `brightsky request` line per HTTP call, to stderr.
