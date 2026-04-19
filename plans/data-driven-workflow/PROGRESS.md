# Data-Driven Workflow — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 0–3 | Fix _apply_substitutions + LoadTestDataAction + registration + demo workflow | TODO | `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/ol_data_driven.json --show` |

See **CONVERSATION_PROMPTS.md** for the exact prompt to paste.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 0 | Fix _apply_substitutions | Engine | Preserve types for pure {{key}} refs (bug fix) | 1 | TODO | `stepper/engine/actions/sub_step_mixin.py` |
| 1 | LoadTestDataAction | Engine | New action class in strategies.py | 1 | TODO | `stepper/engine/actions/strategies.py` |
| 2 | Registration | Engine | Wire into factory.py | 1 | TODO | `stepper/engine/actions/factory.py` |
| 3 | Demo workflow | Flow | ol_data_driven.json | 1 | TODO | `stepper/sites/openlibrary/workflows/ol_data_driven.json` |

## Prerequisites
- `stepper/sites/openlibrary/workflows/ol_search_and_add.json` exists ✓
- `poms/openLibrary/data/testdata.json` exists ✓

## Blocked By
- Nothing
