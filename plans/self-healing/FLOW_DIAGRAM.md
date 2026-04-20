# Self-Healing Planner — Flow Diagram

## Cache Hit Path: No Healing Needed (subsequent runs)

```
StepRunner.run(steps)
        │  step N dispatched
        ▼
[HealingCache.lookup(site, action, param_fingerprint)]
        │
        ├─ cache HIT → inject healed_cfg at priority 0
        │       └─► GlueAction._execute()  (tries healed cfg first)
        │               ├─ success → done ✓  (reporter: "from healing cache")
        │               └─ miss → fall through to normal cfg list
        │
        └─ cache MISS → normal dispatch →
```

## Happy Path: Step Healed on First Attempt

```
StepRunner.run(steps)
        │  step N dispatched
        ▼
[ActionRegistry.create(step.action)]
        │
        ▼
[GlueAction._execute(page, step, resolver)]
        │  FAILS — ElementNotFoundError
        ▼
[retry loop]  attempt 1..max_retry
        │  all retries exhausted → status="failed"
        ▼
[healing loop?]
        │  healer is not None AND max_heal_attempts > 0
        │  AND step.heal is not False
        ▼
[DOMSnapshotCascade.capture(page, step)]
        │  embed-first: MiniLM scores step title vs elements
        │  → threshold decision → minimum payload to AI
        ▼
[AiHealer.heal(step, error, dom_payload)]
        │  if dom_payload.healed_cfg set → no AI call needed
        │  otherwise: Groq → Gemini → Claude Haiku cascade
        │  strips markdown fences
        │  parses JSON → validates action names
        ▼
[StepRunner.run(replacement_steps, ctx)]
        │  recursive call, healer=None
        │
        ├─ all replacement steps PASS
        │       └─► post-heal assertion  (if step.heal_assert is set)
        │               │  url_contains? element_visible? text_contains?
        │               │  pure Playwright checks — no AI, <100ms
        │               │
        │               ├─ all assertions PASS (or no heal_assert defined)
        │               │       └─► status="healed"
        │               │           HealingCache.record(site, action, params, new_cfg)
        │               │           → writes to sites/<site>/healing_overrides.json
        │               │           → reporter logs: old cfg → new cfg diff
        │               │           continue to step N+1
        │               │
        │               └─ assertion FAILS  (wrong element was clicked)
        │                       └─► log "heal passed but assertion failed"
        │                           heal_attempt += 1 → loop back
        │
        └─ replacement steps FAIL
                └─► heal_attempt += 1
                    if heal_attempt < max_heal_attempts → loop back
                    else → surface original error (hard stop or
                            continue_on_failure)
```

## Error Path: All Healing Attempts Exhausted

```
[healing loop — attempt 3/3]
        │
        └─ [ClaudeHealer.heal()] ──► HealingError
                │
                └─ StepRunner logs warning
                   heal_attempt = 3 = max → exit loop
                        │
                        └─ original StepResult(status="failed")
                           surfaced to reporter
                                │
                                ├─ continue_on_failure=true → next step
                                └─ continue_on_failure=false → hard stop
```

## Healing Disabled Path (default)

```
StepRunner.run(steps)
        │  healer=None OR max_heal_attempts=0
        ▼
[retry loop exhausted → status="failed"]
        │
        └─ healing loop: condition False → skipped entirely
                │
                └─ hard stop (unchanged from pre-healing behaviour)
```

## DOMSnapshotCascade — Embed-First Strategy

```
[DOMSnapshotCascade.capture(page, step)]
        │
        ├─ Step 1: Extract all interactive elements
        │       page.evaluate(buttons, inputs, links, selects)
        │       → [{tag, text, role, aria, id, placeholder}, ...]
        │
        ├─ Step 2: Build composite query + embed  (MiniLM-L6-v2, already in memory)
        │       query = step.description + param values
        │       fallback: parse action name if description < 15 chars
        │       embed(query) → vector T
        │       embed(each element: text + aria + placeholder) → vectors E[]
        │       score[i] = cosine_similarity(T, E[i])
        │
        └─ Step 3: Threshold decision tree
                │
                ├─ score ≥ 0.85 + unique match
                │       → DomPayload(healed_cfg=<cfg>, strategy="embed_direct")
                │       → NO AI CALL                            ~0 tokens
                │
                ├─ score ≥ 0.85 + 2+ matches  (ambiguous)
                │       → DomPayload(content=top_N_json, strategy="embed_candidates")
                │       → AiHealer gets top-N candidates only  ~20–40 tokens
                │
                ├─ 0.50 ≤ score < 0.85 + unique best
                │       → scoped DOM area: best_match_selector
                │           .closest('form,main,section,nav,dialog')
                │           .outerHTML → structured JSON
                │       → DomPayload(content=..., strategy="scoped")
                │       → AiHealer gets best + context          ~40–80 tokens
                │
                ├─ 0.50 ≤ score < 0.85 + 2+ matches
                │       → top-N candidates + scoped area
                │       → DomPayload(content=..., strategy="scoped")
                │                                               ~80–150 tokens
                │
                └─ score < 0.50  (all candidates weak)
                        → page.accessibility.snapshot() — full aria tree
                        → DomPayload(content=aria_json, strategy="aria")
                                                                ~200–500 tokens
```

## AiHealer Provider Cascade

```
[AiHealer.heal(step, error, dom_payload)]
        │
        ├─ dom_payload.healed_cfg is set?
        │       └─► build StepConfig from healed_cfg  (NO API call)  ✓
        │
        └─ Build prompt: step + error + dom_payload.content
                │
                ├─ Provider 1: Groq / Qwen-2.5-32b  (~200ms, free)
                │       key rotation: GROQ_API_KEY=key1,key2,key3
                │       same round-robin as AIPickResolver
                │       ├─ success → parse + validate → return ✓
                │       └─ 429/fail → rotate key → try next key
                │               all keys exhausted → next provider
                │
                ├─ Provider 2: Gemini Flash  (~500ms, cheap)
                │       key: GEMINI_API_KEY
                │       ├─ success → parse + validate → return ✓
                │       └─ fail → next provider
                │
                └─ Provider 3: Claude Haiku  (~2s, fallback)
                        key: ANTHROPIC_API_KEY
                        ├─ success → parse + validate → return ✓
                        └─ fail → raise HealingError ✗
```

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `[DOMSnapshotCascade]` | Embed-first cascade — passes minimum tokens to AI |
| `[AiHealer]` | Groq→Gemini→Claude Haiku cascade to suggest replacement steps |
| `[healing loop]` | Wraps DOMSnapshotCascade + AiHealer + recursive run |
| `[StepRunner.run (recursive)]` | Executes replacement steps, no healer |
| `DomPayload.healed_cfg` | Set when embed resolved it — AiHealer skips API call |
| `status="healed"` | New terminal status — step recovered without hard stop |
