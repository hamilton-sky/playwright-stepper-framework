# Commands: brightsky-verify

The real commands for this project, read from its own config (`.github/workflows/ci.yml`,
`pyproject.toml`, `CLAUDE.md`). Approved by a human when the plan is approved. Workers
read this file and must not change it.

The flow runs Smoke before every ticket and Build, Test and Lint after every ticket, so
each must run without asking anything and exit non zero on failure. This project has no
build step and no linter configured, so:
- Build byte-compiles every module, which catches syntax errors. The brief settles it
  (Decided): "Build is `python3 -m compileall -q stepper poms`: the project has no build
  step of its own, and this is the closest real check (syntax of every module)."
- Lint is the browser-free workflow check that CI's "Validate all workflows" step runs.

The requirements and `pip install -e .` are installed for `/usr/bin/python3` on this host
(brief, Decided, 2026-11-01). Smoke was run there and printed `49 passed`. The unit
conftest puts the checkout's own root first on `sys.path`, so a lane worktree tests its
own code without a reinstall. That is why there is no `Setup:` line: running
`pip install -e .` in a lane would repoint the shared interpreter at that lane.

There is no `Run:` line. The feature's entry point
(`python3 -m stepper brightsky verify ...`) is what the plan builds, so it cannot run
before the work is done, and the project's config does not name it. Ticket 09 runs it.

Build: `python3 -m compileall -q stepper poms`
Test: `python3 -m pytest stepper/tests/unit/ -q`
Lint: `python3 stepper/main.py validate`
Smoke: `python3 -m compileall -q stepper poms && python3 -m pytest stepper/tests/unit/test_cli.py -q`
Sensitive: `stepper/brightsky/client.py, stepper/brightsky/config.py, stepper/brightsky/mapping.py, stepper/engine/ai/, stepper/engine/healer/, .github/workflows/, *token*`
Profile: `standard`
Acceptance: `python3 -m pytest plans/brightsky-verify/acceptance -q`
