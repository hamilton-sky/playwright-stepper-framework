# Add the `brightsky verify` command and document the adapter

Type: task
Status: open
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

