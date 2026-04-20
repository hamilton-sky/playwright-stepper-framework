# LLM Transpiler — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1 | ActionSchemaExtractor — reads registry, formats prompt block | TODO | `python -c "from engine.planner.schema_extractor import ActionSchemaExtractor; print('ok')"` |
| 2 | 2 | Ground ClaudePlanner with schema injection | TODO | `python stepper/main.py --task "..." --dry-run` |
| 3 | 3–4 | PlanValidator + dry-run gate in main.py | TODO | `python stepper/main.py --task "..." --dry-run` end-to-end |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | ActionSchemaExtractor | Engine | Reads ActionRegistry, formats schema as prompt block | 1 | TODO | `stepper/engine/planner/schema_extractor.py` |
| 2 | Grounded ClaudePlanner | Engine | Injects schema into system prompt template | 2 | TODO | `stepper/engine/planner/planner.py` |
| 3 | PlanValidator | Engine | Validates generated steps against registry | 3 | TODO | `stepper/engine/planner/validator.py` |
| 4 | Dry-Run Gate | Entry point | --dry-run flag, proposal.json, Y/N prompt | 3 | TODO | `stepper/main.py` |

## Prerequisites
- `ANTHROPIC_API_KEY` set in environment
- If `plans/self-healing/` Phase 0 is already done, skip Conv 1 (schema extractor)
  and Conv 3 (validator) — those files will already exist.

## Blocked By
- Nothing
