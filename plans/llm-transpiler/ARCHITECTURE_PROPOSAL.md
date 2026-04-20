# LLM Transpiler — Architecture Proposal

## Problem Statement
`ClaudePlanner` already converts natural language → `StepConfig`, but it generates
generic action names (`click`, `fill`, `navigate`) that `ActionRegistry` rejects at
runtime. The LLM has no knowledge of which site-specific actions are registered.

## Proposed Solution
Add three thin components to the engine's planner layer — no new layers, no new
dependencies beyond what already exists:

1. **`ActionSchemaExtractor`** — reads the populated `ActionRegistry` and produces a
   schema dict + human-readable prompt block.
2. **Grounded `ClaudePlanner`** — accepts `action_schema` and injects it into the
   system prompt so the LLM only chooses from real action names.
3. **`PlanValidator`** — validates LLM output against the registry before any browser
   action fires.
4. **Dry-run gate** (inline in `main.py`) — saves `proposal.json`, prompts Y/N.

## Three-Layer Breakdown

```
main.py (--task "..." --dry-run)
     │
     ▼
ClaudePlanner.plan(task, action_schema)      ← planner layer (engine-only)
     │  emits [StepConfig] using ol_* names
     ▼
PlanValidator.validate(steps, registry)      ← planner layer (engine-only)
     │  raises PlanValidationError on bad steps
     ▼
DryRunGate → proposal.json + Y/N prompt      ← main.py entry point
     │  author approves
     ▼
StepRunner.run(steps)                        ← runner layer (unchanged)
     │  "action": "ol_ensure_login"
     ▼
GlueAction._execute(page, step, resolver)    ← glue layer (unchanged)
     │  _build_pom(LoginPage, …, page=page, resolver=resolver)
     ▼
POM._resolve_and_click_any(CFG_LIST)         ← POM layer (unchanged)
     │
     ▼
ElementResolver cascade → Playwright
```

## Key Design Decisions

### Decision 1: Extract schema after register_all_sites()
- **Options**: A) extract before site registration (engine actions only),
  B) extract after (all actions including ol_* / sd_*)
- **Chosen**: B — extract after `register_all_sites()` in `main.py`
- **Rationale**: site-specific actions are what the LLM needs; generic engine actions
  alone would still produce unusable plans for site-specific tasks

### Decision 2: Keep ActionRegistry internals unchanged
- **Options**: A) add `get_schema()` public method to `ActionRegistry`,
  B) read `_registry` directly in extractor
- **Chosen**: B — minimal change, no new public API surface
- **Rationale**: `ActionRegistry` is stable; adding a public method for one consumer
  is premature abstraction. If registry is ever refactored, extractor is the only
  update point.

### Decision 3: Backward-compat when action_schema=None
- **Chosen**: `ClaudePlanner` falls back to generic prompt when no schema provided
- **Rationale**: existing unit tests and `--task` usage without site registration
  must keep working; schema is opt-in

### Decision 4: Validation runs even without --dry-run
- **Chosen**: `PlanValidator.validate()` always runs in `--task` mode
- **Rationale**: catching hallucinations before any browser action is always correct;
  the dry-run gate is about human review, not correctness

## New Modules
| Module | Location | Purpose |
|--------|----------|---------|
| `ActionSchemaExtractor` | `stepper/engine/planner/schema_extractor.py` | Registry → schema dict + prompt block |
| `PlanValidator` | `stepper/engine/planner/validator.py` | Validate steps against registry |
| `PlanValidationError` | `stepper/engine/planner/validator.py` | Custom exception |

## Risks
- **LLM still hallucinates despite grounding**: mitigated by `PlanValidator` hard gate
- **Schema prompt grows too large** (many sites): `to_prompt_block()` can truncate to
  top-N most relevant actions in future; for now all sites fit within Claude's context
- **Non-tty stdin blocks in dry-run**: mitigated by `sys.stdin.isatty()` check
