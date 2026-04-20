# Self-Healing Planner — Conversation Guide

Split into 4 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

No external prerequisites — all shared infrastructure is built in Conversation 1.

---

## Conversation 1: Shared Infrastructure (Phase 0)

**Prompt to paste:**
```
Implement Self-Healing Planner Conversation 1 (Phase 0) from
plans/self-healing/IMPLEMENTATION_PLAN.md.

Scope — Phase 0: Shared planner infrastructure
- Create stepper/engine/planner/schema_extractor.py with ActionSchemaExtractor:
  - extract(registry) → dict[str, dict] — reads registry._registry, returns
    {action_name: {description, params}} for each registered action
    - description = first line of class docstring or action_name if none
    - params = _execute() param names minus (self, page, step, resolver, context)
  - to_prompt_block(schema) → str — formats schema as numbered list for prompt injection
- Create stepper/engine/planner/validator.py with:
  - PlanValidationError(message: str, bad_steps: list) — custom exception
  - PlanValidator.validate(steps: list[StepConfig], registry: ActionRegistry) → None
    - Checks every step.action is a key in registry._registry
    - Checks every step has non-empty action and description
    - Collects ALL errors before raising (no short-circuit)
- Update stepper/engine/planner/__init__.py to export ActionSchemaExtractor and PlanValidator
- NOTE: dict_to_step_config already exists in stepper/engine/utils.py — do NOT add a duplicate.
  Verify it is importable as shown below.

Do NOT touch planner.py, step_runner.py, main.py, or healer/ yet.

Verify:
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.planner.schema_extractor import ActionSchemaExtractor
from engine.planner.validator import PlanValidator, PlanValidationError
from engine.utils import dict_to_step_config
from engine.actions.factory import build_default_registry
r = build_default_registry()
schema = ActionSchemaExtractor.extract(r)
print('Schema keys:', list(schema.keys())[:3])
print('PlanValidator:', PlanValidator)
print('dict_to_step_config:', dict_to_step_config)
print('ok')
"

After done, update plans/self-healing/PROGRESS.md Phase 0 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** Schema keys printed, `PlanValidator` and `dict_to_step_config` shown, `ok` printed.
**Files touched:** `stepper/engine/planner/schema_extractor.py`,
`stepper/engine/planner/validator.py`, `stepper/engine/planner/__init__.py`

---

## Conversation 2: AIService + HealerStrategy + DOMSnapshotCascade (Phases 0.5 + 1)

**Prompt to paste:**
```
Conversation 1 is DONE (ActionSchemaExtractor, PlanValidator, dict_to_step_config exist).

Implement Self-Healing Planner Conversation 2 (Phases 0.5 + 1) from
plans/self-healing/IMPLEMENTATION_PLAN.md.

Scope — Phase 0.5: Centralised AI provider layer
- Create stepper/engine/ai/__init__.py (empty package init)
- Create stepper/engine/ai/providers.py with:
  - GroqProvider: reads GROQ_API_KEY (comma-separated for round-robin), async chat(prompt) -> str
  - GeminiProvider: reads GEMINI_API_KEY, async chat(prompt) -> str
  - ClaudeProvider: reads ANTHROPIC_API_KEY, async chat(prompt, model) -> str
  (Mirror the existing backend pattern from engine/resolvers/ai_pick_resolver.py)
- Create stepper/engine/ai/service.py with AIService:
  TASK_CHAINS = {
    "classify": [GroqProvider, GeminiProvider, ClaudeProvider],
    "plan":     [ClaudeProvider],
    "heal":     [GroqProvider, GeminiProvider, ClaudeProvider],
  }
  async chat(self, prompt: str, task_type: str = "classify") -> str
    — tries each provider in chain order, returns first success

Scope — Phase 1: HealerStrategy interface + DOMSnapshotCascade utility
- Create stepper/engine/healer/__init__.py (empty package init)
- Create stepper/engine/healer/interfaces.py with:
  - HealerStrategy (ABC): abstract async heal(step, error, dom_payload) -> list[StepConfig]
  - HealingError(Exception) — raised when healing is not possible
  - DomPayload dataclass: strategy_used: str, content: str, healed_cfg: dict | None, token_estimate: int
- Create stepper/engine/healer/dom_snapshot.py with DOMSnapshotCascade:
  - async capture(page, step) -> DomPayload
  - embed-first cascade using MiniLM-L6-v2 (already loaded by element_resolver):
    1. Embed _build_query(step) → vector T; embed each interactive element → vectors E[]
       score ≥ 0.85 + unique match → return DomPayload(strategy_used="embed_direct",
         healed_cfg=<generated from element attrs>, content="", token_estimate=0)
       score ≥ 0.85 + 2+ matches → top-N JSON → DomPayload(strategy_used="embed_candidates", ~20-40 tok)
       0.50 ≤ score < 0.85 → best match + scoped DOM area → DomPayload(strategy_used="scoped", ~40-150 tok)
       score < 0.50 → page.accessibility.snapshot() → DomPayload(strategy_used="aria", ~200-500 tok)
  - _build_query(step) → uses step.description + step.extra values (NOT step.params — that field
    does not exist; use step.extra)
  - Interactive element extraction:
    elements = await page.evaluate("""() =>
      [...document.querySelectorAll(
        'button,a,input,select,textarea,[role],[aria-label]'
      )].map(el => ({
        tag: el.tagName, text: el.textContent?.trim().slice(0,80),
        role: el.getAttribute('role'),
        aria: el.getAttribute('aria-label'),
        id: el.id, placeholder: el.getAttribute('placeholder')
      }))
    """)

Do NOT touch step_runner.py, main.py, or create AiHealer yet.

Verify:
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.ai.service import AIService
from engine.ai.providers import ClaudeProvider, GroqProvider, GeminiProvider
from engine.healer.interfaces import HealerStrategy, HealingError, DomPayload
from engine.healer.dom_snapshot import DOMSnapshotCascade
import inspect
assert inspect.isabstract(HealerStrategy), 'HealerStrategy must be ABC'
print('AIService:', AIService)
print('HealerStrategy:', HealerStrategy)
print('DOMSnapshotCascade:', DOMSnapshotCascade)
print('ok')
"

After done, update plans/self-healing/PROGRESS.md Phases 0.5 and 1 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `AIService`, `HealerStrategy`, `DOMSnapshotCascade` importable, `ok` printed.
**Files touched:** `stepper/engine/ai/__init__.py`, `stepper/engine/ai/providers.py`,
`stepper/engine/ai/service.py`, `stepper/engine/healer/__init__.py`,
`stepper/engine/healer/interfaces.py`, `stepper/engine/healer/dom_snapshot.py`

---

## Conversation 3: AiHealer (Phase 2)

**Prompt to paste:**
```
Conversations 1–2 are DONE:
- Shared infrastructure (ActionSchemaExtractor, PlanValidator, dict_to_step_config)
- AIService with Groq/Gemini/Claude providers in stepper/engine/ai/
- HealerStrategy ABC + DomPayload + DOMSnapshotCascade in stepper/engine/healer/

Implement Self-Healing Planner Conversation 3 (Phase 2) from
plans/self-healing/IMPLEMENTATION_PLAN.md.

Scope — Phase 2: AiHealer implementation
- Create stepper/engine/healer/ai_healer.py with AiHealer(HealerStrategy):
  - __init__(action_schema: dict, ai_service: AIService)
  - async heal(step: StepConfig, error: str, dom_payload: DomPayload) -> list[StepConfig]:
    1. If dom_payload.healed_cfg is not None → embed resolved it; build StepConfig directly,
       NO AI call
    2. Otherwise build system prompt: "You are a browser automation healer. Given a failed
       step, its error, and the current page context, return a JSON array of replacement
       steps using ONLY these registered actions: {action_block}"
       Inject ActionSchemaExtractor.to_prompt_block(self._action_schema) for {action_block}
    3. Build user message: JSON of original step + error string + dom_payload.content
    4. Call ai_service.chat(prompt, task_type="heal"); strip markdown fences
    5. Parse JSON → [dict_to_step_config(s) for s in raw]
    6. If result is a single dict, wrap in list
    7. Validate each replacement step's action is in action_schema keys
    8. Raise HealingError if response is empty array or invalid JSON
- Import dict_to_step_config from engine.utils (NOT dict_to_step — that name does not exist)
- Import ActionSchemaExtractor from engine.planner.schema_extractor
- Import HealerStrategy, HealingError, DomPayload from engine.healer.interfaces
- Import AIService from engine.ai.service

Do NOT touch step_runner.py or main.py yet.

Verify:
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.healer.ai_healer import AiHealer
from engine.healer.interfaces import HealerStrategy
assert issubclass(AiHealer, HealerStrategy)
print('AiHealer is a HealerStrategy:', True)
print('ok')
"

After done, update plans/self-healing/PROGRESS.md Phase 2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `AiHealer is a HealerStrategy: True`, `ok` printed.
**Files touched:** `stepper/engine/healer/ai_healer.py`

---

## Conversation 4: StepRunner Healing Loop + CLI Integration (Phases 3–4)

**Prompt to paste:**
```
Conversations 1–3 are DONE:
- Shared infrastructure (ActionSchemaExtractor, PlanValidator, dict_to_step_config)
- AIService + Groq/Gemini/Claude providers in stepper/engine/ai/
- HealerStrategy ABC + DomPayload + DOMSnapshotCascade in stepper/engine/healer/
- AiHealer in stepper/engine/healer/ai_healer.py

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
