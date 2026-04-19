# Data-Driven Workflow — Implementation Plan

## Overview
Adds a single engine-level action `load_test_data` that reads a JSON array from
disk and stores it in `context.collected_items`. The existing `for_each_item`
action already spreads dict-item fields as `{{item.<key>}}` substitutions, so
no changes to `ForEachItemAction` are needed. Registration is one line in
`factory.py`. A demo workflow ties it all together.

## Layer Architecture

```
Flow (JSON)  →  Engine action (strategies.py)  →  ExecutionContext
     │                    │                               │
[load_test_data]   LoadTestDataAction            context.collected_items = [...]
     │
[for_each_item]    ForEachItemAction (existing)  iterates, exposes {{item.*}}
     │
[run_workflow]     RunWorkflowAction (existing)  runs sub-workflow per row
```

---

## Phase 0: Fix `_apply_substitutions` type preservation (required prerequisite)

**Layer:** Engine
**Files:**
- `stepper/engine/actions/sub_step_mixin.py` — add pure-reference type-preservation check

**Details:**
`_substitute` (planner.py) preserves types for pure `{{key}}` references. `_apply_substitutions`
does not — it always stringifies via `str(v)`. This causes `{{item.limit}}` to arrive as `"5"`
instead of `5`, breaking any POM that uses the value arithmetically (e.g. `while len(collected) < limit`).

Add a type-preserving early-return at the top of the `isinstance(obj, str)` branch:

```python
def _apply_substitutions(obj, subs: dict):
    if isinstance(obj, str):
        # Pure reference: preserve original type (mirrors _substitute in planner.py)
        stripped = obj.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            key = stripped[2:-2].strip()
            if key in subs:
                return subs[key]
        for k, v in subs.items():
            token = f"{{{{{k}}}}}"
            if token in obj:
                v_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                obj = obj.replace(token, v_str)
        return obj
    ...
```

**Verify:** existing `for_each_item` workflows still pass; numeric fields from data rows
arrive as their original type in downstream glue code.

---

## Phase 1: LoadTestDataAction class (strategies.py)

**Layer:** Engine
**Files:**
- `stepper/engine/actions/strategies.py` — add `LoadTestDataAction` class at the end

**Details:**
- `action_name = "load_test_data"`
- Reads `step.extra.get("path")` — accepts relative (resolved from cwd) or absolute
- If path is relative, emit `logger.warning(f"load_test_data: resolving relative path '{path}' from cwd {Path.cwd()}")` before resolving, to help authors debug wrong-directory runs
- Parses JSON; expects a list (`isinstance(data, list)`)
- Sets `context.collected_items = data`
- Returns `StepResult(status="passed")` on success; descriptive `status="failed"` errors otherwise

**Verify:** unit check — not yet testable end-to-end (needs Phase 2 + 3)

---

## Phase 2: Register LoadTestDataAction (factory.py)

**Layer:** Engine
**Files:**
- `stepper/engine/actions/factory.py` — import `LoadTestDataAction`, add `.register(LoadTestDataAction())` to `build_default_registry`

**Details:**
- Import alongside the other strategies at the top of `build_default_registry`
- Registration call: `.register(LoadTestDataAction())`
- No constructor args needed (stateless action)

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/ol_data_driven.json --show`
(workflow created in Phase 3)

---

## Pre-Phase 3 Verification: RunWorkflowAction var merging

**Status: VERIFIED SAFE** — `RunWorkflowAction._execute` merges vars via `_substitute`
(planner.py line 996), which already preserves types for pure `{{key}}` references.
It does NOT call `_apply_substitutions`. Typed values from data rows survive the hand-off
to the sub-workflow unchanged. No additional fix needed.

---

## Phase 3: Demo workflow (ol_data_driven.json)

**Layer:** Flow
**Files:**
- `stepper/sites/openlibrary/workflows/ol_data_driven.json` — NEW

**Details:**
Workflow structure:
1. `load_test_data` — load `poms/openLibrary/data/testdata.json`
2. `for_each_item` with sub-steps:
   a. `run_workflow` — call `ol_search_and_add.json` with vars `query`, `max_year`, `limit` sourced from `{{item.query}}`, `{{item.max_year}}`, `{{item.limit}}`

The `ol_search_and_add.json` already accepts `query`, `max_year`, `limit` as variables.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/ol_data_driven.json --show`

---

## Prerequisites
- `stepper/sites/openlibrary/workflows/ol_search_and_add.json` exists (it does)
- `poms/openLibrary/data/testdata.json` exists (it does)

## Key Decisions
- **No changes to `ForEachItemAction`**: it already supports `{{item.<key>}}` via the `subs[f"item.{key}"] = val` loop (line ~370 in strategies.py). We leverage this.
- **Engine-level action, not site-specific**: `load_test_data` is generic — any site can use it, so it belongs in `strategies.py` + `factory.py`, not in a glue file.
- **`context.collected_items` as the hand-off**: this is the standard interface for `for_each_item`. No new context fields needed.
