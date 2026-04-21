# Self-Healing Planner — Conversation Guide

**Progress: ALL CONVERSATIONS DONE. Phases 0–4 complete. Phase 5 (HealingCache) deferred.**

---

## Conversation 4: StepRunner Healing Loop + CLI Integration (Phases 3–4)

**Prompt to paste:**
```
Conversations 1–3 are DONE. The following modules exist and all imports verified OK:
- engine/planner/schema_extractor.py  — ActionSchemaExtractor (extract, to_prompt_block)
- engine/planner/validator.py         — PlanValidator, PlanValidationError
- engine/ai/__init__.py, providers.py — GroqProvider, GeminiProvider, ClaudeProvider
- engine/ai/service.py                — AIService (chat with task_type routing)
- engine/healer/__init__.py
- engine/healer/interfaces.py         — HealerStrategy (ABC), HealingError, DomPayload
- engine/healer/dom_snapshot.py       — DOMSnapshotCascade (embed-first cascade)
- engine/healer/ai_healer.py          — AiHealer (implements HealerStrategy)

Implement Self-Healing Planner Conversation 4 (Phases 3–4) from
plans/self-healing/IMPLEMENTATION_PLAN.md.

Scope — Phase 3: StepRunner healing loop
- Modify StepRunner in stepper/engine/runner/step_runner.py:
  - Add healer: HealerStrategy | None = None and
    max_heal_attempts: int = 0 to __init__ signature
  - After the existing retry loop produces a failed result, add a healing loop:
    * Only runs when: result.status == "failed" AND self._healer is not None
      AND getattr(step, 'heal', True) is not False
      AND heal_attempt < min(self._max_heal_attempts, 3)
    * Each attempt: DOMSnapshotCascade.capture(page, step) → AiHealer.heal() →
      run replacement steps via recursive self.run(replacement_steps, ctx) with healer=None
    * If all replacement steps pass: set result.status = "healed"
    * If step has heal_assert: run _run_heal_assert(page, step.heal_assert); if it fails,
      continue to next heal attempt
    * If healing raises or replacement steps fail: log warning, continue loop
    * After all healing attempts exhausted: surface original error (hard stop or
      continue_on_failure as before)
  - Add _run_heal_assert(page, spec: dict) -> bool private helper (see IMPLEMENTATION_PLAN)
  - Import DOMSnapshotCascade from engine.healer.dom_snapshot
  - Import HealerStrategy from engine.healer.interfaces

- Modify stepper/engine/interfaces.py:
  - Add "healed" to StepResult status comment (alongside "passed", "failed", "skipped", "warned")
  - Add heal: bool = True field to StepConfig dataclass
  - Add heal_assert: dict | None = None field to StepConfig dataclass

Scope — Phase 4: CLI + settings integration
- Modify stepper/main.py:
  - Add --heal N argument (int, default 0, metavar="N",
    help="Max self-healing attempts per step (default 0 = disabled)")
  - In run(): if args.heal > 0 and ANTHROPIC_API_KEY is set:
    * schema = ActionSchemaExtractor.extract(action_registry)
    * ai_service = AIService()
    * healer = AiHealer(action_schema=schema, ai_service=ai_service)
    * pass healer=healer, max_heal_attempts=args.heal to StepRunner
  - If args.heal == 0: pass healer=None (zero behaviour change for existing runs)

Do NOT touch POM files, glue files, or any exam/ tests.

Verify:
pytest exam/
python stepper/main.py \
  --workflow stepper/sites/openlibrary/workflows/search_and_add.json \
  --show
# All existing tests pass; healing not triggered on normal successful runs

Then verify --heal flag is wired (no ANTHROPIC_API_KEY needed for this check):
python stepper/main.py --help | grep heal

After done, update plans/self-healing/PROGRESS.md Phases 3–4 to DONE and
overall Status to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** All exam tests pass, `--heal` visible in `--help` output.
**Files touched:** `stepper/engine/runner/step_runner.py`,
`stepper/engine/interfaces.py`, `stepper/main.py`

---

## Note: Phase 5 (HealingCache + selector writeback)

Phase 5 is designed and documented in IMPLEMENTATION_PLAN.md but is deferred from this
4-conversation plan. It can be implemented as a follow-up plan once Phases 0–4 are stable.
