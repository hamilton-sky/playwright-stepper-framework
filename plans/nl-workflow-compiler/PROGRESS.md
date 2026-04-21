# NL Workflow Compiler — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1–2 | AIService compile task type + compiler module (NLCompiler, PromptBuilder, OutputParser) | TODO | `python -c "from engine.compiler.compiler import NLCompiler; print('ok')"` |
| 2 | 3–4 | CLI --compile flag in main.py + site config registry | TODO | `python stepper/main.py --compile "log in, add item, view cart" --site saucedemo --show` |
| 3 | E2E | End-to-end: compile saucedemo flow → run compiled JSON | TODO | compiled JSON runs successfully with `--workflow` |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | AIService compile task | Engine/AI | Add compile chain to AIService | 1 | TODO | `stepper/engine/ai/service.py` |
| 2 | Compiler module | Engine | NLCompiler + PromptBuilder + OutputParser | 1 | TODO | `stepper/engine/compiler/` |
| 3 | CLI flag | Engine/CLI | --compile --site --output args in main.py | 2 | TODO | `stepper/main.py` |
| 4 | Site config | Engine | SITE_CONFIGS dict for base URLs | 2 | TODO | `stepper/engine/compiler/site_registry.py` |

## Prerequisites
- `GROQ_API_KEY` or `ANTHROPIC_API_KEY` in `.env`
- Playwright browsers installed

## Blocked By
- Nothing
