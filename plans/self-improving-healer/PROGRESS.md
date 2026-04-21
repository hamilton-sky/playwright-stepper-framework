# Self-Improving Healer — Progress

## Status: IN PROGRESS

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1 | Visual bridge — is_visible/is_enabled pre-check before cascade | DONE | `python -c "from engine.healer.visual_bridge import VisualBridge; print('ok')"` |
| 2 | 2 | Local heal cache — HealCache class + wire into StepRunner | DONE | cache HIT on second run of same broken workflow |
| 3 | 3 | --apply-heals CLI — read suggestions, show diff, patch workflow JSON | TODO | `python stepper/main.py --apply-heals <workflow> --yes` patches file |
| 4 | 4 | StepRunner refactor — extract _run_step, _run_retry_loop, _run_heal_loop | TODO | `pytest exam/ -x -q` passes; `run()` ~50 lines |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | Visual Bridge | Engine | is_visible/is_enabled check before DOMSnapshotCascade | 1 | DONE | `engine/healer/visual_bridge.py`, `engine/runner/step_runner.py` |
| 2 | Heal Cache | Engine | Persistent per-site JSON cache, checked before cascade | 2 | DONE | `engine/healer/healing_cache.py`, `engine/runner/step_runner.py` |
| 3 | --apply-heals | Engine/CLI | Read suggestions, diff, patch workflow JSON | 3 | TODO | `stepper/main.py` |
| 4 | StepRunner Refactor | Engine | Extract _run_step/_run_retry_loop/_run_heal_loop; shrink run() to ~50 lines | 4 | TODO | `engine/runner/step_runner.py` |

## Prerequisites
- Existing healer stack works: DOMSnapshotCascade, AiHealer, heal_suggestions.json written by StepRunner
- No dependency on nl-workflow-compiler

## Blocked By
- Nothing
