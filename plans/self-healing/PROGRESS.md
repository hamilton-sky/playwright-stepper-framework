# Self-Healing Planner — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 0 | Shared infrastructure (ActionSchemaExtractor, PlanValidator, dict_to_step_config) | TODO | `python -c "from engine.planner.schema_extractor import ActionSchemaExtractor; print('ok')"` |
| 2 | 0.5 + 1 | AIService (Groq/Gemini/Claude providers) + HealerStrategy + DOMSnapshotCascade | TODO | `python -c "from engine.ai.service import AIService; from engine.healer.interfaces import HealerStrategy; print('ok')"` |
| 3 | 2 | AiHealer implementation (multi-provider via AIService) | TODO | `python -c "from engine.healer.ai_healer import AiHealer; print('ok')"` |
| 4 | 3–4 | StepRunner healing loop + CLI --heal flag | TODO | `pytest exam/ && python stepper/main.py --workflow ... --heal 2 --show` |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 0 | Shared Infrastructure | Engine | ActionSchemaExtractor, PlanValidator | 1 | TODO | `stepper/engine/planner/schema_extractor.py`, `stepper/engine/planner/validator.py` |
| 0.5 | AIService | Engine | Centralised LLM provider layer (Groq/Gemini/Claude) | 2 | TODO | `stepper/engine/ai/providers.py`, `stepper/engine/ai/service.py` |
| 1 | HealerStrategy + DOMSnapshotCascade | Engine | Interface ABC + embed-first DOM capture utility | 2 | TODO | `stepper/engine/healer/interfaces.py`, `stepper/engine/healer/dom_snapshot.py` |
| 2 | AiHealer | Engine | Multi-provider replacement step generator (Groq→Gemini→Claude) | 3 | TODO | `stepper/engine/healer/ai_healer.py` |
| 3 | StepRunner healing loop | Engine | Wire healer into runner after retry loop | 4 | TODO | `stepper/engine/runner/step_runner.py`, `stepper/engine/interfaces.py` |
| 4 | CLI + settings integration | Entry point | --heal flag, StepConfig heal/heal_assert fields | 4 | TODO | `stepper/main.py`, `stepper/engine/interfaces.py` |
| 5 | HealingCache | Engine | Persist healed cfgs to healing_overrides.json | deferred | DEFERRED | `stepper/engine/healer/healing_cache.py` |

## Prerequisites
- `ANTHROPIC_API_KEY` set in environment (needed for ClaudeProvider fallback; Groq handles most heals)

## Blocked By
- Nothing

## Known naming notes
- `dict_to_step_config` is the correct function name in `stepper/engine/utils.py` — NOT `dict_to_step`
- `step.extra` is the action-specific params bag on StepConfig — NOT `step.params` (field doesn't exist)
