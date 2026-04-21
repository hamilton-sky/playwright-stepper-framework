# NL Workflow Compiler Part 2 — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1–2 | ARIAFilter module + LiveLoopCompiler skeleton | TODO | `python -c "from engine.compiler.live_loop import LiveLoopCompiler; print('ok')"` |
| 2 | 3 | Enhanced AiHealer with full workflow context | TODO | `python -c "import inspect; from engine.healer.ai_healer import AiHealer; assert 'all_steps' in inspect.signature(AiHealer.heal).parameters; print('ok')"` |
| 3 | 4 | --live CLI flag + auto-save + end-to-end test | TODO | `python stepper/main.py --live "log in, add item, checkout" --site saucedemo --show` |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | ARIAFilter | Engine | 3 filter strategies + dynamic selection | 1 | TODO | `stepper/engine/compiler/aria_filter.py` |
| 2 | LiveLoopCompiler | Engine | Per-page loop: snapshot → plan → execute → detect nav | 1 | TODO | `stepper/engine/compiler/live_loop.py` |
| 3 | Enhanced AiHealer | Engine | Optional full context (all_steps, index, vars, aria) | 2 | TODO | `stepper/engine/healer/ai_healer.py`, `interfaces.py` |
| 4 | CLI --live + auto-save | Engine/CLI | --live flag, live_workflow(), save JSON, wire healer context | 3 | TODO | `stepper/main.py` |

## Prerequisites
- plans/nl-workflow-compiler/ Conversations 1–2 DONE
- `stepper/engine/compiler/` module exists with NLCompiler, PromptBuilder, OutputParser, site_registry.py
- `stepper/engine/ai/service.py` has "compile" task type

## Blocked By
- plans/nl-workflow-compiler part-1 must be DONE
