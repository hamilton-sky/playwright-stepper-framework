# LLM Transpiler — Implementation Plan

## Overview
Ground `ClaudePlanner` with the real `ActionRegistry` schema so natural-language tasks
emit valid site-specific `StepConfig` lists. Add JSON Schema validation to catch
hallucinated steps before execution, and a `--dry-run` gate so authors review
`proposal.json` before the browser opens.

## Layer Architecture

```
main.py (--task / --dry-run)
     │
     ▼
ClaudePlanner.plan(task, action_schema=schema)   ← engine/planner/planner.py
     │  emits [StepConfig]
     ▼
PlanValidator.validate(steps, registry)          ← engine/planner/validator.py
     │  raises PlanValidationError on bad steps
     ▼
DryRunGate(steps, path="artifacts/proposal.json")← main.py inline / bootstrap helper
     │  saves JSON, prompts Y/N
     ▼
StepRunner.run(steps)                            ← engine/runner/step_runner.py
```

---

## Phases

### Phase 1: ActionSchemaExtractor (Engine — no browser, no POM)
**Layer:** Engine (`stepper/engine/planner/`)
**Files:**
- `stepper/engine/planner/schema_extractor.py` — NEW: `ActionSchemaExtractor` class
- `stepper/engine/planner/__init__.py` — export `ActionSchemaExtractor`

**Details:**
- `ActionSchemaExtractor.extract(registry: ActionRegistry) → dict[str, dict]`
- Reads `registry._registry` (the internal dict of `action_name → ActionStrategy`)
- For each action, captures: `action_name`, `docstring` (first line of class docstring
  or `action_name` if none), `params` (inspect `_execute` signature minus
  `page/step/resolver/context`)
- Returns schema dict keyed by action name; value is `{description, params}`
- Also exposes `to_prompt_block(schema) → str` — formats schema as a numbered list
  suitable for injection into the Claude system prompt

**Verify:** `python -c "from engine.planner.schema_extractor import ActionSchemaExtractor; print('ok')"`

---

### Phase 2: Grounded ClaudePlanner
**Layer:** Engine (`stepper/engine/planner/planner.py`)
**Files:**
- `stepper/engine/planner/planner.py` — MODIFY: `ClaudePlanner.__init__` + `plan()`
- `stepper/engine/planner/planner.py` — MODIFY: `SYSTEM_PROMPT` becomes a template

**Details:**
- Add `action_schema: dict | None = None` param to `ClaudePlanner.__init__`
- Replace the hardcoded action list in `SYSTEM_PROMPT` with a `{action_block}` placeholder
- In `plan()`, build the system prompt by injecting
  `ActionSchemaExtractor.to_prompt_block(self._action_schema)` when schema is provided;
  fall back to the old generic list when schema is `None` (backward-compat)
- In `main.py`, after `register_all_sites(...)`, call
  `ActionSchemaExtractor.extract(action_registry)` and pass the result to `ClaudePlanner`

**Verify:** `python stepper/main.py --task "search for Dune on OpenLibrary" --dry-run --show`
(should produce steps using `ol_*` action names)

---

### Phase 3: PlanValidator
**Layer:** Engine (`stepper/engine/planner/`)
**Files:**
- `stepper/engine/planner/validator.py` — NEW: `PlanValidator`, `PlanValidationError`
- `stepper/engine/planner/__init__.py` — export `PlanValidator`

**Details:**
- `PlanValidationError(message, bad_steps: list)` — custom exception
- `PlanValidator.validate(steps: list[StepConfig], registry: ActionRegistry) → None`
  - Checks every step's `action` is in `registry._registry`
  - Checks every step has non-empty `action` and `description` fields
  - Collects ALL errors before raising (don't short-circuit on first bad step)
- Called in `main.py` immediately after `planner.plan()` in `--task` mode

**Verify:** manual: pass a step with `action="fake_action"` and confirm `PlanValidationError` raised

---

### Phase 4: Dry-Run Gate
**Layer:** Entry point (`stepper/main.py`)
**Files:**
- `stepper/main.py` — MODIFY: add `--dry-run` arg, `_dry_run_gate()` helper
- `stepper/bootstrap/` — no changes needed

**Details:**
- Add `parser.add_argument("--dry-run", action="store_true")` in `main()`
- Pass `dry_run: bool = False` to `run()`
- After `PlanValidator.validate()`, if `dry_run=True`:
  - Serialize steps to JSON, write to `stepper/artifacts/proposal.json`
  - Print each step's `action + description` to stdout
  - Prompt `"Proceed? [y/N] "` — read from stdin
  - If not `y`/`Y`: print "Aborted." and `return []`
  - If yes: continue to `StepRunner.run(steps)`
- `--dry-run` with `--workflow` also triggers the gate (load steps, validate, prompt)

**Verify:**
```bash
python stepper/main.py \
  --task "Log in to OpenLibrary and collect 3 Asimov books" \
  --dry-run
# Expected: proposal.json written, steps printed, Y/N prompt shown
```

---

---

### Phase 3b: SummaryReporter — Heal Rate Artifact (reporting)
**Layer:** Engine (`stepper/engine/reporter/reporters.py`)
**Files:**
- `stepper/engine/reporter/reporters.py` — MODIFY: `ConsoleReporter.finish_suite()` and `JsonReporter.finish_suite()`

**Details:**
The existing `ConsoleReporter.finish_suite()` counts `passed` and `failed`. Extend it
to also count `healed` (steps recovered by `ClaudeHealer`) and emit a heal-rate line:

```
  Result: 8/10 passed  (1 failed, 1 healed — heal rate: 10%)
```

In `JsonReporter`, add a `"heal_rate"` key to the summary object:
```json
{
  "passed": 8, "failed": 1, "healed": 1, "total": 10,
  "heal_rate_pct": 10.0
}
```

This surfaces AI-recovery as a **first-class metric**: a rising heal rate signals that
site UI is drifting and POM cfg lists need updating — before hard failures accumulate.

**Note:** `status="healed"` is defined in `plans/self-healing/` Phase 3. This phase
depends on self-healing being implemented. Add it in the same conversation as
self-healing Conv 3 or as a follow-up immediately after.

**Verify:**
```bash
# After self-healing is implemented:
python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json --heal 2
# JSON report contains heal_rate_pct field; console prints heal rate line
```

---

## Prerequisites
- `ClaudePlanner` already exists and works (confirmed in `planner.py`)
- `ActionRegistry` is populated via `register_all_sites()` before schema extraction
- `ANTHROPIC_API_KEY` set in environment (for `--task` mode)

**Note:** `ActionSchemaExtractor`, `PlanValidator`, and `dict_to_step` may already exist
if `plans/self-healing/` Phase 0 was implemented first. In that case, skip Phase 1 and
Phase 3 (schema extractor + validator) and proceed directly to Phase 2 (grounding
ClaudePlanner) and Phase 4 (dry-run gate).

## Key Decisions
- **Schema extraction reads `registry._registry` directly** — no new public API on
  `ActionRegistry`; keeps the change minimal and non-breaking.
- **Backward-compat when `action_schema=None`** — `ClaudePlanner` falls back to the
  generic prompt so existing `--task` usage and unit tests still work.
- **Dry-run defaults to `N`** on non-interactive stdin (safe for CI pipelines).
- **Validation runs even without dry-run** in `--task` mode — catches hallucinations
  before any browser page opens.
