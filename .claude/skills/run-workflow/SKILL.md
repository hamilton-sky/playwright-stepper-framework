---
name: run-workflow
description: Run a declarative JSON workflow through stepper/main.py.
argument-hint: "[workflow-name-or-path] [--show] [--site <site>]"
---

Run a workflow through the stepper engine.

## Pre-flight

If no argument is provided, list available workflows:
```bash
python stepper/main.py list [--site <site>]
```
Show the list and ask the user to pick one.

## Parse $ARGUMENTS

- A name or a full path both work — the CLI resolves a bare name across all
  sites and reports close matches when it cannot
- `--show` → watch the browser (omit for headless, which is the default)
- `--site <site>` → only affects `list`, not `run`

## Run the workflow

```bash
python stepper/main.py run <name-or-path> [--show]
```

To check a workflow without launching a browser first:
```bash
python stepper/main.py validate <name-or-path>
```

Use a generous timeout (300000ms) — workflows can be slow.

## After running

- Exit code 0 → "Workflow completed successfully." Show step summary if available in output.
- Exit code non-0 → Show the error, identify which step failed (look for step name in output), suggest whether it's a locator issue (check the POM's `Locator` for that element), a config issue (check the site's `config.py`), or a network/auth issue.
