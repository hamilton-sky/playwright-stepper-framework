# Data-Driven Workflow — Edge Cases

## Category 1: Bad file input

### EC-1.1: `extra.path` missing
- **Trigger**: workflow step has no `path` key under `extra`
- **Expected behavior**: step fails with `"load_test_data: missing extra.path"`
- **Handled in**: Phase 1 — early return in `LoadTestDataAction._execute`

### EC-1.2: File not found
- **Trigger**: path points to a non-existent file
- **Expected behavior**: step fails with `"load_test_data: file not found: <path>"`
- **Handled in**: Phase 1 — `Path.exists()` check before open

### EC-1.3: JSON is an object, not an array
- **Trigger**: data file contains `{}` at the top level instead of `[...]`
- **Expected behavior**: step fails with `"load_test_data: expected a JSON array"`
- **Handled in**: Phase 1 — `isinstance(data, list)` guard

### EC-1.4: Empty array
- **Trigger**: data file is `[]`
- **Expected behavior**: step passes, `for_each_item` is a no-op (0 iterations)
- **Handled in**: existing `ForEachItemAction` behaviour — iterates over empty list

---

## Category 2: Missing keys in data rows

### EC-2.1: Row missing a key referenced in sub-workflow
- **Trigger**: row has no `max_year` but `{{item.max_year}}` is in the sub-workflow
- **Expected behavior**: substitution leaves `{{item.max_year}}` as a literal string;
  the sub-workflow may fail downstream with a type error
- **Handled in**: `_apply_substitutions` (after Phase 0 fix) — if key is absent from
  subs, falls through to the string-replace loop which leaves token as-is; author must
  ensure data rows are complete

---

## Category 3: Iteration failures

### EC-3.1: One row's sub-workflow fails
- **Trigger**: `ol_search_and_add.json` fails for row 2 (e.g., network error)
- **Expected behavior**: `for_each_item` logs the error, takes an error screenshot,
  and continues with row 3 (`stop_on_failure=False` is the default)
- **Handled in**: existing `ForEachItemAction` error handler (no change needed)

---

## Known Limitations
- `load_test_data` always overwrites `context.collected_items`; if a previous step
  also populated it, that data is lost. This is intentional — the action is a
  deliberate "load from file" source.
- Relative paths are resolved from `Path.cwd()` (the working directory when stepper
  is invoked), not from the workflow file's location. Authors should run stepper
  from the repo root.
