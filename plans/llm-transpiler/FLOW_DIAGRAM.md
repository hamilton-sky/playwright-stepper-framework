# LLM Transpiler — Flow Diagram

## Happy Path: --task with --dry-run

```
python main.py --task "..." --dry-run
        │
        ▼
[register_all_sites(registry)]
        │  populates registry with ol_*, sd_*, pt_* actions
        ▼
[ActionSchemaExtractor.extract(registry)]
        │  returns {ol_ensure_login: {...}, ol_collect_books: {...}, ...}
        ▼
[ClaudePlanner.plan(task, action_schema=schema)]
        │  Claude API call with grounded system prompt
        │  returns raw JSON array
        ▼
[ClaudePlanner — strip markdown fences]
        │  if single object → wrap in list
        ▼
[json.loads → [dict_to_step(s) for s in raw]]
        │  returns [StepConfig, StepConfig, ...]
        ▼
[PlanValidator.validate(steps, registry)]
        │
        ├─ all actions known + fields valid ──► continue
        └─ any error ──────────────────────► raise PlanValidationError
                                                    │
                                                    └─ main() prints errors, exits
        │
        ▼
[DryRunGate] (only when --dry-run)
        │  write stepper/artifacts/proposal.json
        │  print numbered step list
        │  prompt "Proceed? [y/N] "
        │
        ├─ stdin not tty ──► "Non-interactive — aborting." return []
        ├─ answer != y/Y ──► "Aborted." return []
        └─ answer == y/Y ──► continue
        │
        ▼
[StepRunner.run(steps)]
        │  dispatches each step by action name
        ▼
[ActionRegistry.create(step.action)]
        │  "ol_ensure_login" → OLEnsureLoginAction instance
        ▼
[GlueAction._execute(page, step, resolver, ctx)]
        │  _build_pom(LoginPage, driver, url, page=page, resolver=resolver)
        ▼
[POM._resolve_and_click_any(BUTTON_CFG)]
        │
        ├─ Phase 1: RoleResolver ──► unique match → click
        ├─ Phase 2: SemanticFilter (MiniLM)
        └─ Phase 3: AI Pick (Groq → Gemini → Claude)
```

## Error Path: PlanValidationError

```
[PlanValidator.validate(steps, registry)]
        │
        └─ step.action == "click" not in registry
                │
                └─ PlanValidationError(
                     "Unknown actions: ['click']",
                     bad_steps=[step]
                   )
                        │
                        └─ main() catches, prints error list, sys.exit(1)
```

## Schema Injection Detail

```
ClaudePlanner.__init__(action_schema=schema)
        │
        ▼
[ActionSchemaExtractor.to_prompt_block(schema)]
        │  returns:
        │  "ol_ensure_login  — Ensure user is logged in to OpenLibrary
        │   ol_collect_books — Search and collect book items
        │   ol_add_to_shelf  — Add a book to the reading shelf
        │   ..."
        ▼
[SYSTEM_PROMPT_TEMPLATE.format(action_block=block)]
        │  injected into Claude messages[system]
        ▼
[Claude API → constrained to registered action names]
```

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `[ActionSchemaExtractor]` | Reads registry._registry, formats schema |
| `[ClaudePlanner]` | Calls Claude API with grounded prompt |
| `[PlanValidator]` | Hard gate — rejects unknown/malformed actions |
| `[DryRunGate]` | Human review checkpoint, writes proposal.json |
| `[StepRunner]` | Existing runner — unchanged by this feature |
| `[GlueAction]` | Existing glue — unchanged by this feature |
