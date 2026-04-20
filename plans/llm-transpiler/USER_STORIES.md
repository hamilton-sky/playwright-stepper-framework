# LLM Transpiler — User Stories

## Context
`ClaudePlanner` already converts natural language → `StepConfig` list, but its system
prompt lists generic action names (`navigate`, `click`, `fill`) that don't exist in the
`ActionRegistry` after site registration. When a user runs `--task "..."`, the planner
produces steps that the runner immediately rejects as "Unknown action". The transpiler
feature grounds the planner: it extracts the real registered action schema, injects it
into the system prompt, validates the LLM output against that schema, and gates
execution behind a dry-run review step so the user can inspect `proposal.json` before
anything touches the browser.

## Stories

### Story 1.1: Grounded Action Vocabulary
**As a** test author, **I want** the LLM planner to only emit action names that are
actually registered (e.g. `ol_ensure_login`, `sd_add_to_cart`), **so that** natural-
language tasks don't fail immediately with "Unknown action" errors.

**Acceptance Criteria:**
- [ ] `ActionSchemaExtractor.extract(registry)` returns a dict of `action_name → {params, description}`
- [ ] `ClaudePlanner` accepts an optional `action_schema` argument
- [ ] When `action_schema` is provided, the system prompt lists only those action names
- [ ] A task prompt for OpenLibrary produces steps using `ol_*` actions, not `click`/`fill`

**Edge Cases:**
- Registry is empty (no sites registered) — extractor returns empty dict, planner warns
- Action has no declared params — schema entry shows `params: {}` rather than crashing

---

### Story 1.2: JSON Schema Validation Gate
**As a** test author, **I want** the LLM-generated plan validated against a JSON Schema
before execution, **so that** malformed or hallucinated steps are caught before any
browser action fires.

**Acceptance Criteria:**
- [ ] A `StepConfigSchema` JSON Schema document covers required fields (`action`, `description`)
- [ ] `PlanValidator.validate(steps, registry)` raises `PlanValidationError` for unknown actions
- [ ] `PlanValidator` raises `PlanValidationError` for structurally invalid steps
- [ ] Valid plans pass through unchanged

**Edge Cases:**
- LLM wraps output in markdown code fences — already stripped in `ClaudePlanner.plan()`
- LLM returns a single object instead of array — validator catches and reports clearly

---

### Story 1.3: Dry-Run Proposal Gate
**As a** test author, **I want** `python stepper/main.py --task "..." --dry-run` to save
the proposed plan to `proposal.json` and pause for my approval, **so that** I can review
and tweak the plan before any browser action fires.

**Acceptance Criteria:**
- [ ] `--dry-run` flag added to `main.py` argument parser
- [ ] In dry-run mode, plan is saved to `stepper/artifacts/proposal.json`
- [ ] Execution pauses and prints the plan summary to stdout
- [ ] User is prompted Y/N; `N` exits cleanly, `Y` continues to `StepRunner`
- [ ] `--dry-run` with `--workflow` also works (useful for reviewing JSON workflows)

**Edge Cases:**
- `proposal.json` parent dir doesn't exist — created automatically
- User pipes stdin (non-interactive) — defaults to `N` (safe)
