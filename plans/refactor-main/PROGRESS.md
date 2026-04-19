# Refactor main.py — Progress

## Status: IN PROGRESS

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1–4 | Extract settings, resolver, reporters, browser helpers in main.py | DONE | `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json --show` |
| 2 | 5–6 | Create per-site register.py files + auto-discovery in main.py | DONE | `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json` |
| 3 | 7 | Fix RunWorkflowAction temporal coupling | TODO | `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json` |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | Extract settings | main.py | `_load_settings_safe()` replaces two identical try/except blocks | 1 | DONE | `stepper/main.py` |
| 2 | Extract resolver | main.py | `_build_resolver(use_visual_ai)` isolates ElementResolver construction | 1 | DONE | `stepper/main.py` |
| 3 | Extract reporters | main.py | `_build_reporters(…)` isolates all four reporter types | 1 | DONE | `stepper/main.py` |
| 4 | Extract browser launch | main.py | `_launch_browser(pw, …)` deduplicates launcher dict | 1 | DONE | `stepper/main.py` |
| 5 | Per-site register.py | Glue | One `register(registry)` per site folder | 2 | DONE | `stepper/sites/*/register.py` |
| 6 | Auto-discovery | main.py | `_register_all_sites()` globs for register.py files | 2 | DONE | `stepper/main.py` |
| 7 | Temporal coupling fix | main.py | Reorder `RunWorkflowAction` registration to after `StepRunner` construction; remove coupling comment | 3 | TODO | `stepper/main.py` |

## Prerequisites
- All existing exam tests pass: `pytest exam/`
- No uncommitted changes to `stepper/main.py` before starting

## Blocked By
- Nothing
