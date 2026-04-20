# LLM Transpiler — Conversation Guide

Split into 3 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: ActionSchemaExtractor (Phase 1)

> **Note:** If `plans/self-healing/` was implemented first, `ActionSchemaExtractor` and
> `PlanValidator` already exist. In that case, skip to Conversation 2.

**Prompt to paste:**
```
Implement LLM Transpiler Conversation 1 (Phase 1) from
plans/llm-transpiler/IMPLEMENTATION_PLAN.md.

First check: if stepper/engine/planner/schema_extractor.py already exists with
ActionSchemaExtractor, skip this conversation and go to Conversation 2.

Scope — Phase 1: ActionSchemaExtractor
- Create stepper/engine/planner/schema_extractor.py with class ActionSchemaExtractor
- ActionSchemaExtractor.extract(registry) reads registry._registry (dict of
  action_name → ActionStrategy) and returns dict[str, dict] with keys:
  {description: str, params: list[str]}
  - description = first line of the action class docstring, or the action_name if none
  - params = parameter names of _execute() minus (self, page, step, resolver, context)
- ActionSchemaExtractor.to_prompt_block(schema) returns a formatted string listing
  each action name + description on one line, suitable for Claude system prompt injection
- Update stepper/engine/planner/__init__.py to export ActionSchemaExtractor

Do NOT touch planner.py, main.py, or validator.py yet.

Verify: python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.planner.schema_extractor import ActionSchemaExtractor
from engine.actions.factory import build_default_registry
r = build_default_registry()
schema = ActionSchemaExtractor.extract(r)
print(list(schema.keys()))
print(ActionSchemaExtractor.to_prompt_block(schema)[:200])
print('ok')
"

After done, update plans/llm-transpiler/PROGRESS.md Phase 1 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** List of registered action names printed, first 200 chars of
prompt block shown, `ok` printed.
**Files touched:** `stepper/engine/planner/schema_extractor.py`,
`stepper/engine/planner/__init__.py`

---

## Conversation 2: Grounded ClaudePlanner (Phase 2)

**Prompt to paste:**
```
Conversation 1 is DONE (ActionSchemaExtractor exists in
stepper/engine/planner/schema_extractor.py).

Implement LLM Transpiler Conversation 2 (Phase 2) from
plans/llm-transpiler/IMPLEMENTATION_PLAN.md.

Scope — Phase 2: Ground ClaudePlanner with action schema injection
- Modify ClaudePlanner in stepper/engine/planner/planner.py:
  - Add action_schema: dict | None = None param to __init__
  - Convert SYSTEM_PROMPT to a template with an {action_block} placeholder
    where the hardcoded action list currently sits
  - In plan(), build the final system prompt by calling
    ActionSchemaExtractor.to_prompt_block(self._action_schema) when schema is provided;
    fall back to a generic placeholder list when schema is None (backward-compat)
- Modify stepper/main.py in the --task branch of run():
  - After register_all_sites(...) is called, extract the schema:
    schema = ActionSchemaExtractor.extract(action_registry)
  - Pass schema to ClaudePlanner: ClaudePlanner(action_schema=schema)

Three-layer rules to observe:
- No POM or glue imports in planner.py — planner is engine-only
- Do NOT change JsonFilePlanner or StaticPlanner

Do NOT implement PlanValidator or --dry-run yet.

Verify (requires ANTHROPIC_API_KEY):
python stepper/main.py --task "Log in to OpenLibrary" --show
# Should produce steps using ol_* action names, not generic click/fill

If you don't have ANTHROPIC_API_KEY, verify by unit-checking the prompt:
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.planner.planner import ClaudePlanner
from engine.planner.schema_extractor import ActionSchemaExtractor
from engine.actions.factory import build_default_registry
from bootstrap.infra import register_all_sites
from pathlib import Path
r = build_default_registry()
register_all_sites(r, Path('stepper'))
schema = ActionSchemaExtractor.extract(r)
p = ClaudePlanner(action_schema=schema)
import inspect
src = inspect.getsource(p.__class__)
assert 'ol_ensure_login' not in src  # not hardcoded in source
print('Schema keys injected:', list(schema.keys())[:5])
print('ok')
"

After done, update plans/llm-transpiler/PROGRESS.md Phase 2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** Steps printed use `ol_ensure_login` etc., not `click`/`fill`.
**Files touched:** `stepper/engine/planner/planner.py`, `stepper/main.py`

---

## Conversation 3: PlanValidator + Dry-Run Gate (Phases 3–4)

**Prompt to paste:**
```
Conversations 1–2 are DONE (ActionSchemaExtractor grounding ClaudePlanner with real
action schema).

Implement LLM Transpiler Conversation 3 (Phases 3–4) from
plans/llm-transpiler/IMPLEMENTATION_PLAN.md.

Scope — Phase 3: PlanValidator
- Create stepper/engine/planner/validator.py with:
  - PlanValidationError(message: str, bad_steps: list) — custom exception
  - PlanValidator.validate(steps: list[StepConfig], registry: ActionRegistry) → None
    - Checks every step.action is a key in registry._registry
    - Checks every step has non-empty action and description
    - Collects ALL errors before raising (don't short-circuit)
- Update stepper/engine/planner/__init__.py to export PlanValidator
- Call PlanValidator.validate(steps, action_registry) in run() in stepper/main.py
  immediately after planner.plan() in the --task branch

Scope — Phase 4: Dry-Run Gate
- Add --dry-run argument to the argparse parser in stepper/main.py main()
- Add dry_run: bool = False param to run()
- After PlanValidator.validate(), if dry_run is True:
  - Serialize steps to JSON dicts and write to stepper/artifacts/proposal.json
    (create parent dir if needed)
  - Print a numbered list of "action: description" to stdout
  - Prompt "Proceed? [y/N] " — read from stdin
  - If stdin is not a tty (piped/CI), default to N and print "Non-interactive — aborting."
  - If answer is not y/Y: print "Aborted." and return []
  - If y/Y: continue to StepRunner.run(steps)
- --dry-run with --workflow also triggers the gate after JsonFilePlanner.plan()

Do NOT modify POM or glue files.

Verify:
python stepper/main.py \
  --workflow stepper/sites/openlibrary/workflows/search_and_add.json \
  --dry-run
# Should: print steps, prompt Y/N, write stepper/artifacts/proposal.json

After done, update plans/llm-transpiler/PROGRESS.md Phases 3–4 to DONE and
overall Status to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `proposal.json` written, steps listed, Y/N prompt shown.
**Files touched:** `stepper/engine/planner/validator.py`,
`stepper/engine/planner/__init__.py`, `stepper/main.py`
