# LLM Transpiler — Happy Flow

## Overview
A test author types a natural-language task. The transpiler grounds the LLM in the
real action vocabulary, validates the plan, shows a dry-run summary, and — after
approval — hands off to StepRunner which executes each action through the normal
Glue → POM → resolver cascade.

## Step-by-Step Happy Flow

### Step 1: Author runs --task with --dry-run
- **Command**: `python stepper/main.py --task "Log in to OpenLibrary, search for Asimov, add 3 books to my shelf" --dry-run`
- **Stepper does**: builds `ActionRegistry`, calls `register_all_sites()`, extracts schema

### Step 2: Schema extraction
- **Action**: `ActionSchemaExtractor.extract(registry)`
- **Stepper does**: reads `registry._registry`, produces dict of all registered action names
  including `ol_ensure_login`, `ol_collect_books`, `ol_add_to_shelf`, `ol_store_count`
- **Output**: schema dict passed to `ClaudePlanner`

### Step 3: Grounded planning
- **Action**: `ClaudePlanner.plan(task, action_schema=schema)`
- **Stepper does**: injects schema into system prompt; calls Claude API
- **LLM output**: JSON array using only `ol_*` action names
- **Result**: `[StepConfig(ol_ensure_login, ...), StepConfig(ol_collect_books, ...), StepConfig(ol_add_to_shelf, ...)]`

### Step 4: Validation
- **Action**: `PlanValidator.validate(steps, registry)`
- **Stepper does**: confirms every `step.action` is in the registry; all required fields present
- **Result**: passes silently

### Step 5: Dry-run gate
- **Action**: `_dry_run_gate(steps, path="stepper/artifacts/proposal.json")`
- **Stepper does**: serializes plan to `proposal.json`, prints numbered step list:
  ```
  1. ol_ensure_login   — Ensure user is logged in to OpenLibrary
  2. ol_collect_books  — Search for Asimov, collect up to 3 results
  3. ol_add_to_shelf   — Add each collected book to reading shelf
  Proceed? [y/N]
  ```
- **Author**: reviews, types `y`

### Step 6: StepRunner execution
- **Action**: `StepRunner.run(steps)`
- **Stepper does**: each step dispatched through `ActionRegistry` → `GlueAction._execute()`
  → `POM._resolve_and_*()` → `ElementResolver` cascade → Playwright

## End State
- `stepper/artifacts/proposal.json` contains the approved plan
- Books are added to the OpenLibrary shelf
- Test report written to `stepper/reports/`

## Success Indicators
- [ ] `proposal.json` contains only `ol_*` action names
- [ ] No "Unknown action" errors from `ActionRegistry`
- [ ] All steps complete without `PlanValidationError`
- [ ] Books appear on the reading shelf after run
