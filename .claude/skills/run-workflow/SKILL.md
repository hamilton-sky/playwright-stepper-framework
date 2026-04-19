---
name: run-workflow
description: Run a declarative JSON workflow through stepper/main.py.
argument-hint: "[workflow-name-or-path] [--show] [--site <site>]"
---

Run a workflow through the stepper engine.

## Pre-flight

If no argument is provided, list available workflows:
```bash
find stepper/sites -name "*.json" -path "*/workflows/*"
```
Show the list and ask the user to pick one.

## Parse $ARGUMENTS

- If given a full path → use as-is
- If given a name (e.g. `ol_smoke_test`) → search for `stepper/sites/*/workflows/*<name>*.json`
- `--show` → add `--show` flag to watch the browser (omit for headless, which is the default)
- `--site <site>` → narrow the search to `stepper/sites/<site>/workflows/`

## Run the workflow

```bash
python stepper/main.py --workflow <resolved-path> [--show]
```

Use a generous timeout (300000ms) — workflows can be slow.

## After running

- Exit code 0 → "Workflow completed successfully." Show step summary if available in output.
- Exit code non-0 → Show the error, identify which step failed (look for step name in output), suggest whether it's a locator issue (check pom cfg list), a config issue (check site config.py), or a network/auth issue.
