# Data-Driven Workflow — Conversation Guide

Single conversation — small, self-contained engine addition.
After the conversation, **commit your changes** before moving on.

---

## Conversation 1: LoadTestDataAction + Registration + Demo Workflow (Phases 1–3)

**Prompt to paste:**
```
Implement Data-Driven Workflow Conversation 1 (Phases 0–3) from
plans/data-driven-workflow/IMPLEMENTATION_PLAN.md.

Scope:

Phase 0 — Fix _apply_substitutions in sub_step_mixin.py
  - Add a pure-reference type-preservation early-return at the top of the
    `isinstance(obj, str)` branch in `_apply_substitutions`:
    if the entire string is `{{key}}` and the key exists in subs, return subs[key] directly.
  - This mirrors the behaviour of `_substitute` in planner.py and fixes a bug where
    numeric values from for_each_item data rows arrive as strings, breaking POM arithmetic.
  - See IMPLEMENTATION_PLAN.md Phase 0 for the exact code pattern.

Phase 1 — Add LoadTestDataAction to strategies.py
  - Add a new class `LoadTestDataAction(ActionStrategy)` near the end of
    `stepper/engine/actions/strategies.py` (before or after RunWorkflowAction).
  - action_name = "load_test_data"
  - Reads `step.extra.get("path")` — resolve relative paths from Path.cwd()
  - If path is relative, emit logger.warning BEFORE resolving:
      logger.warning(f"load_test_data: resolving relative path '{path}' from cwd {Path.cwd()}")
  - Parses JSON; must be a list — fail with a clear error if it's a dict or missing
  - Sets context.collected_items = data (the parsed list)
  - Returns StepResult(status="passed") on success
  - No constructor arguments needed (stateless)

Note: RunWorkflowAction.vars merging is SAFE — it uses _substitute (planner.py), which
  already preserves types for pure {{key}} references. No additional fix needed there.

Phase 2 — Register in factory.py
  - In `stepper/engine/actions/factory.py`, inside `build_default_registry`:
    - Import LoadTestDataAction alongside the other strategies
    - Add `.register(LoadTestDataAction())` to the fluent chain

Phase 3 — Demo workflow
  - Create `stepper/sites/openlibrary/workflows/ol_data_driven.json`
  - Step 1: load_test_data from "poms/openLibrary/data/testdata.json"
  - Step 2: for_each_item with sub-steps:
      - run_workflow pointing at "stepper/sites/openlibrary/workflows/ol_search_and_add.json"
        with vars: query={{item.query}}, max_year={{item.max_year}}, limit={{item.limit}}

Do NOT modify ForEachItemAction — it already supports {{item.<key>}} substitution.
Do NOT touch exam/ tests, other workflows, or POM files.

Verify: python stepper/main.py --workflow stepper/sites/openlibrary/workflows/ol_data_driven.json --show

After done, update plans/data-driven-workflow/PROGRESS.md phases 0–3 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `ol_data_driven.json` runs, iterates over all 4 testdata entries, calling `ol_search_and_add.json` once per row with the correct variables.

**Files touched:**
- `stepper/engine/actions/sub_step_mixin.py` (bug fix — type preservation)
- `stepper/engine/actions/strategies.py` (new class)
- `stepper/engine/actions/factory.py` (import + register)
- `stepper/sites/openlibrary/workflows/ol_data_driven.json` (new file)
