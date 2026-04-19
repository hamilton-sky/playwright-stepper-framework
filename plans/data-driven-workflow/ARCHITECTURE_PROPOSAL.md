# Data-Driven Workflow — Architecture Proposal

## Problem Statement
Workflow variables are currently hardcoded in JSON `"variables"` blocks. Running
the same workflow with N different input sets requires N copies of the file or
manual re-runs with `--vars` overrides. We need a way to drive a workflow from an
external data file without any framework machinery changes beyond a single new action.

## Proposed Solution
Add `LoadTestDataAction` — an engine-level action that reads a JSON array into
`context.collected_items`. The existing `ForEachItemAction` already iterates over
that context field and exposes each dict row's keys as `{{item.<key>}}` template
variables. Combined with `RunWorkflowAction`, this gives a complete data-driven
loop with zero changes to the existing iteration or substitution machinery.

## Three-Layer Breakdown

```
Flow layer  (ol_data_driven.json)
     │  "action": "load_test_data"   extra.path → testdata.json
     ▼
Engine      (LoadTestDataAction)
     │  context.collected_items = [{query,max_year,limit,...}, ...]
     ▼
Flow layer  "action": "for_each_item"
     │  exposes {{item.query}}, {{item.max_year}}, {{item.limit}}
     ▼
Engine      (RunWorkflowAction — existing)
     │  merges vars into ol_search_and_add.json variables
     ▼
Glue + POM  (existing ol_* actions — unchanged)
```

## Key Design Decisions

### Decision 1: Engine action, not glue action
- **Options considered**: (A) engine action in strategies.py, (B) site-specific glue action
- **Chosen**: A
- **Rationale**: the action is completely generic (no selectors, no site knowledge);
  placing it in the engine makes it reusable across all sites and keeps the glue
  layer free of file I/O

### Decision 2: Reuse context.collected_items instead of a new context field
- **Options considered**: (A) set `context.collected_items`, (B) add new field
  `context.test_data_rows`
- **Chosen**: A
- **Rationale**: `for_each_item` already reads `context.collected_items` and
  spreads dict keys as `{{item.*}}`; reusing it means zero changes to any existing
  action or runner code

### Decision 3: No changes to ForEachItemAction
- The `{{item.<key>}}` substitution already exists (see `subs[f"item.{key}"] = val`
  in `ForEachItemAction._execute`). No extension needed.

## New Action Names
| Action name | Registered in |
|---|---|
| `load_test_data` | `factory.py` → `build_default_registry` |

## Risks
- **Path confusion**: relative paths resolve from cwd, not from workflow file location.
  Mitigation: `LoadTestDataAction` emits a `logger.warning` whenever a relative path is
  used, surfacing the resolved cwd so authors can diagnose wrong-directory runs immediately.
  Users should always run from repo root.
- **RunWorkflowAction re-stringifying typed vars**: VERIFIED NOT AN ISSUE.
  `RunWorkflowAction` merges vars via `_substitute` (planner.py), which preserves types
  for pure `{{key}}` references. Numeric fields from data rows arrive typed in the sub-workflow.
- **Type coercion — real bug requiring a fix before this feature works**:
  `_substitute` (planner.py) preserves types for pure `{{key}}` references —
  so `"{{limit}}"` with `variables.limit = 5` yields the integer `5`.
  `_apply_substitutions` (sub_step_mixin.py, used by `ForEachItemAction`) does NOT
  preserve types — it always calls `str(v)`, so `"{{item.limit}}"` with
  `subs["item.limit"] = 5` yields the string `"5"`.
  This causes `while len(collected) < "5"` → `TypeError` in `collect_books_under_year`.
  **Mitigation (required)**: patch `_apply_substitutions` to match `_substitute`:
  if the entire string is a pure `{{key}}` reference, return the typed value directly
  before falling through to the string-replace loop. No other file needs changing.
