# Self-Healing Planner — Architecture Proposal

## Problem Statement
When a `GlueAction` fails after all configured retries, the framework hard-stops.
There is no recovery mechanism — the author must manually edit the workflow or cfg
list, re-run, and hope the DOM hasn't changed again. This makes the framework brittle
against small site updates.

## Proposed Solution
Add a `HealerStrategy` interface and an `AiHealer` implementation. Wire a healing
loop into `StepRunner.run()` that fires only after all normal retries are exhausted.
Healing is disabled by default (zero API calls, zero behaviour change) and enabled
via `--heal N` CLI flag or `settings.max_heal_attempts` in the workflow JSON.

`AiHealer` uses the same provider cascade already proven in `AIPickResolver`:
Groq (free, rotation keys) → Gemini Flash → Claude Haiku.

## Three-Layer Breakdown

```
Workflow JSON (unchanged)
     │  "action": "ol_add_to_shelf"
     ▼
StepRunner.run()                          ← MODIFIED
     │  step fails after retry loop
     ▼
DOMSnapshotCascade.capture(page, step)    ← NEW (engine/healer/)
     │  embed-first strategy cascade:
     │  1. embed step title vs interactive elements (MiniLM, free)
     │  2. scoped DOM area around failed element
     │  3. full aria snapshot (last resort)
     │  → only passes minimum needed tokens to AI
     ▼
HealerStrategy.heal(step, error, dom)     ← NEW interface (engine/healer/)
     │
     ▼
AiHealer (default impl)                   ← NEW (engine/healer/)
     │  Groq/Qwen (rotation keys) → Gemini Flash → Claude Haiku
     │  returns [StepConfig] replacement
     ▼
StepRunner.run([replacement_steps], ctx)  ← recursive call (no healer)
     │  success → mark original "healed"
     │  failure → next heal attempt or surface original error
     ▼
GlueAction._execute()                     ← UNCHANGED
     │
     ▼
POM layer                                 ← UNCHANGED
     │
     ▼
ElementResolver cascade → Playwright      ← UNCHANGED
```

## Key Design Decisions

### Decision 1: Healing loop inside StepRunner, not ActionStrategy
- **Options**: A) in `ActionStrategy.execute()` base class, B) in `StepRunner.run()`
- **Chosen**: B — StepRunner
- **Rationale**: `ActionStrategy.execute()` handles retry for a single action type;
  it doesn't know a step has exhausted all retries. `StepRunner` is the only place
  that has the full picture: step index, retry count, page, context, and factory.

### Decision 2: Recursive StepRunner.run() for replacement steps
- **Options**: A) recursive call with `healer=None`, B) separate execution method
- **Chosen**: A — recursive, healer omitted
- **Rationale**: reuses all existing observer/reporter/screenshot/when-eval logic.
  Passing `healer=None` prevents infinite healing loops.

### Decision 3: AiHealer uses Groq-first provider cascade + embed-first DOM strategy
- **Providers**: Groq/Qwen (free, ~200ms) → Gemini Flash (~500ms) → Claude Haiku (~2s)
- **Rationale**: Mirrors the proven `AIPickResolver` cascade. Groq is free with
  multiple rotation keys (`GROQ_API_KEY=key1,key2,key3`) and handles most cases.
  Haiku is the fallback of last resort — correctness backstopped by `PlanValidator`.
- **DOM strategy**: embed-first cascade (see Decision 8) means AI often receives
  <80 tokens rather than a full DOM dump — providers stay cheap even at scale.

### Decision 6: DOMSnapshot is an embed-first cascade, not a flat capture
- **Options**: A) flat structured JSON, B) embed-first cascade with progressive fallback
- **Chosen**: B — embed-first cascade
- **Rationale**: Reuses MiniLM-L6-v2 already loaded by the resolver (zero extra cost).
  Most heals resolve in Strategy 1 or 2 with <80 tokens to the AI. Only genuinely
  broken pages reach Strategy 3 (full aria snapshot). Raw HTML is never sent unless
  all structured strategies fail.
- **Implementation**: `DOMSnapshotCascade.capture(page, step)` — see Decision 8.

### Decision 8: Embed-first DOM cascade with threshold decision tree
- **Rationale**: Before touching any AI provider, embed the step title and all
  interactive element descriptions with MiniLM and compare cosine similarity.
  This gates the entire AI call — high-confidence unique matches never reach the
  network at all. The threshold decision tree controls payload size precisely:

```
  Embed step title → vector T
  Embed each element's {text, aria-label, placeholder, name} → vectors E[]
  score[i] = cosine_similarity(T, E[i])

  score ≥ 0.85 + unique match   → generate healed cfg  (NO AI call, 0 tokens)
  score ≥ 0.85 + 2+ matches     → top-N candidates only (~20–40 tokens)
  0.50 ≤ score < 0.85 + unique  → best match + scoped DOM area (~40–80 tokens)
  0.50 ≤ score < 0.85 + 2+      → top-N + scoped DOM area (~80–150 tokens)
  score < 0.50                  → full aria snapshot (~200–500 tokens)
```

- **Token savings**: 80% of real-world heals are expected to resolve in the first
  two tiers (<80 tokens) because the element still exists but with changed attributes.
  Only true DOM restructuring (score < 0.50) reaches the full snapshot.

### Decision 4: max_heal_attempts clamped to 3
- **Rationale**: More than 3 attempts indicates a structural problem, not a transient
  one. Capping prevents runaway API costs on genuinely broken workflows.

### Decision 5: Disabled by default (max_heal_attempts=0)
- **Rationale**: Healing adds latency and API cost. Opt-in keeps existing behaviour
  identical; authors enable it intentionally for flaky-prone workflows.

### Decision 7: Centralised AIService before adding a third LLM caller
- **Options**: A) `ClaudeHealer` calls Claude API directly (third scatter point), B) extract `stepper/engine/ai/` first
- **Chosen**: B — extract AIService in Phase 0.5
- **Rationale**: `ai_pick_resolver.py` and `planner.py` already call LLMs independently. A third scattered caller creates three places to update when providers change or a new model ships. `AIService.chat(prompt, task_type)` routes to the right provider chain per task — adding Qwen, OpenAI, etc. = one new provider class, zero changes to callers.

## New Modules

| Module | Location | Purpose |
|--------|----------|---------|
| `AIService` | `stepper/engine/ai/service.py` | Single LLM entry point; routes by task_type |
| `GroqProvider` / `GeminiProvider` / `ClaudeProvider` | `stepper/engine/ai/providers.py` | One class per LLM provider (~20 lines each) |
| `HealerStrategy` (ABC) | `stepper/engine/healer/interfaces.py` | Swappable healer contract |
| `HealingError` | `stepper/engine/healer/interfaces.py` | Signals healing failure |
| `DOMSnapshotCascade` | `stepper/engine/healer/dom_snapshot.py` | Embed-first cascade: MiniLM gate → scoped area → aria tree |
| `AiHealer` | `stepper/engine/healer/ai_healer.py` | LLM-based replacement planner; Groq → Gemini → Claude cascade |

## Modified Files

| File | Change |
|------|--------|
| `stepper/engine/runner/step_runner.py` | Add healing loop after retry loop |
| `stepper/engine/interfaces.py` | Add `"healed"` status + `heal: bool` to StepConfig |
| `stepper/main.py` | Add `--heal N` flag, build + inject healer |

## Risks
- **Healing adds latency per failed step** — mitigated by Haiku model choice and
  opt-in default
- **Claude suggests a step that passes but does the wrong thing** — mitigated by
  keeping PlanValidator + the resolver cascade as the correctness gate
- **Recursive run() creates complex stack traces** — mitigated by passing `healer=None`
  to prevent further recursion; depth is bounded at 1
