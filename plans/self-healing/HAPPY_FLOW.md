# Self-Healing Planner — Happy Flow

## Overview
A workflow step fails because the site's DOM changed since the workflow was authored
(e.g. a button's label changed from "Add to List" to "Add to Reading List"). Instead
of hard-stopping, StepRunner captures the current DOM, asks Claude to suggest a
replacement step, and executes it. The workflow completes successfully.

## Step-by-Step Happy Flow

### Step 1: Normal step execution begins
- **Action**: `ol_add_to_shelf` (or any glue action)
- **Stepper does**: `ActionRegistry.create("ol_add_to_shelf")` → `GlueAction._execute()`
- **Browser state**: Book detail page is open

### Step 2: Step fails after retries
- **Stepper does**: `ElementResolver` cascade finds 0 matches for the button cfg list;
  all `step.retry` attempts exhausted
- **Result**: `StepResult(status="failed", error="ElementNotFoundError: ...")`
- **Browser state**: Page unchanged (no click happened)

### Step 3: DOM snapshot captured
- **Stepper does**: `DOMSnapshot.capture(page, max_chars=8000)`
- **Result**: Simplified HTML string with `<script>`, `<style>`, `<svg>` stripped,
  truncated to 8000 chars — enough for Claude to see the button structure

### Step 4: ClaudeHealer called
- **Action**: `ClaudeHealer.heal(step, error, dom_snapshot)`
- **Stepper does**: Claude API call (Haiku) with:
  - Original step JSON: `{"action": "ol_add_to_shelf", "description": "Add book to shelf"}`
  - Error: `"ElementNotFoundError: no match for 'Add to List'"`
  - DOM snapshot (8000 chars of page HTML)
  - Registered action schema (action names + descriptions)
- **LLM output**: `[{"action": "ol_add_to_shelf", "description": "Add book using updated label", "extra": {"label": "Add to Reading List"}}]`

### Step 5: Replacement steps executed
- **Stepper does**: `StepRunner.run([replacement_step], ctx)` — recursive call
- **Browser state**: Button found with new label, clicked successfully
- **Result**: `StepResult(status="passed")`

### Step 6: Original step marked healed
- **Stepper does**: `dataclasses.replace(original_result, status="healed", error=None)`
- **Stepper does**: continues to next step in workflow; no hard stop

## End State
- Workflow completes all steps
- One step is marked `status="healed"` in the test report
- No manual workflow edits were needed

## Success Indicators
- [ ] `StepResult.status == "healed"` for the recovered step
- [ ] Subsequent steps execute normally
- [ ] `ClaudeHealer.heal()` called exactly once (healing succeeded on first attempt)
- [ ] Test report shows `healed` result alongside `passed` results
