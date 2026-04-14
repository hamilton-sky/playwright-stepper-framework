---
name: test
description: Run pytest tests for the stepper framework (exam suite or specific test/mark).
argument-hint: "[all|exam|<test-name>|<file-path>] [--headless] [-k <mark>]"
---

Run tests for the stepper framework.

## Target: $ARGUMENTS (default: all exam tests)

### Parse flags from arguments:
- `--headless` → pass through to pytest via `HEADLESS=true` env or pytest flag
- `-k <mark>` → filter by pytest mark or keyword
- A specific file path → run that file only
- A test name → pass to `-k`

### Default (no args or "all"):
```bash
pytest exam/ -v
```

### Specific test file:
```bash
pytest exam/tests/test_openlibrary_exam.py -v
```

### Filter by keyword/mark:
```bash
pytest exam/ -k "<mark>" -v
```

### With headless browser:
```bash
pytest exam/ -v --headless
```

## After running

Report results clearly:
- Total passed / failed / skipped
- For any failure: show the test name, the assertion that failed, and the last few lines of the traceback
- If all pass: confirm "All tests passed."

Do NOT suggest code changes unless the user asks — just report results.
