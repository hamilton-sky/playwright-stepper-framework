---
name: test
description: Run pytest tests for the stepper framework (unit suite, plain-POM example, or a specific test/mark).
argument-hint: "[all|unit|example|<test-name>|<file-path>] [--headless] [-k <mark>]"
---

Run tests for the stepper framework.

## Target: $ARGUMENTS (default: the unit suite)

### Parse flags from arguments:
- `--headless` → pass through to pytest via `HEADLESS=true` env or pytest flag
- `-k <mark>` → filter by pytest mark or keyword
- A specific file path → run that file only
- A test name → pass to `-k`

### Default (no args, "all" or "unit") — fast, no browser, no network:
```bash
pytest stepper/tests/unit/ -v
```

### Plain-POM example suite (real browser + OpenLibrary credentials):
```bash
cd examples/plain_pom && pytest tests/ -v
```

### Stepper integration tests (real browser):
```bash
pytest stepper/tests/ --ignore=stepper/tests/unit -v
```

### Specific test file:
```bash
pytest <file-path> -v
```

### Filter by keyword/mark:
```bash
pytest stepper/tests/unit/ -k "<mark>" -v
```

Start with the unit suite: it needs no browser and no credentials, so it is the
fastest way to tell whether a change broke something.

## After running

Report results clearly:
- Total passed / failed / skipped
- For any failure: show the test name, the assertion that failed, and the last few lines of the traceback
- If all pass: confirm "All tests passed."

Do NOT suggest code changes unless the user asks — just report results.
