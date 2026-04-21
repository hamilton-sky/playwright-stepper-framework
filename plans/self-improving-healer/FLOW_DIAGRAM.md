# Self-Improving Healer — Flow Diagram

## Full Healing Decision Tree (after step fails)

```
Step fails
        │
        ▼
[VisualBridge.check(page, step)]       ← NEW Phase 1
        │
        ├─ "hidden"  → fail: "element hidden — state issue"
        │               (no AI call, no cascade)
        │
        ├─ "disabled"→ fail: "element disabled — check flow"
        │               (no AI call, no cascade)
        │
        └─ None / "ok" → continue
                │
                ▼
[HealCache.get(step)]                  ← NEW Phase 2
        │
        ├─ HIT → apply healed_cfg directly
        │           └─ replacement runs
        │                   success → done (0 tokens)
        │                   fail    → "[HealCache] stale"
        │                             → fall through to cascade
        │
        └─ MISS → continue
                │
                ▼
[DOMSnapshotCascade.capture(page, step)]   ← existing
        │
        ├─ score ≥ 0.85 unique  → embed_direct (0 tokens)
        │                          healed_cfg ready
        │
        ├─ score ≥ 0.85 ambiguous → embed_candidates
        │                           (~30 tokens to AI)
        │
        ├─ score 0.50–0.85 → scoped DOM (~100 tokens to AI)
        │
        └─ score < 0.50    → ARIA walk  (~350 tokens to AI)
                │
                ▼
[AiHealer.heal(step, error, dom,       ← existing + context
               all_steps, current_index, context_vars)]
        │
        ├─ fast path: dom.healed_cfg not None → apply (0 tokens)
        │
        └─ slow path: AIService.chat(task_type="heal")
                │  Groq → Gemini → Claude
                │
                ▼
        healed_cfg applied
                │
                ├─ HealCache.put(step, healed_cfg)  ← NEW Phase 2
                └─ heal_suggestions.json appended   ← existing
```

---

## --apply-heals Flow (Phase 3, runs separately)

```
python stepper/main.py --apply-heals checkout.json
        │
        ▼
apply_heals(workflow_path, auto_yes)
        │
        ├─ load heal_suggestions.json
        │       not found → error + exit
        │
        ├─ load workflow JSON
        │
        ├─ for each suggestion:
        │       match by description field
        │       no match  → warn + skip
        │       1+ match  → collect patch
        │
        ├─ print diff:
        │   Step N "<desc>":
        │     BEFORE: {original element}
        │     AFTER:  {healed element}
        │
        ├─ auto_yes=False → prompt [Y/n]
        │   'n' → exit without patching
        │
        └─ patch element fields in workflow JSON
                write back with indent=2
                print "N heal(s) applied. Commit to make permanent."
```

---

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `VisualBridge` | Pre-cascade gate: is element hidden or disabled? |
| `HealCache` | Persistent per-site JSON store; zero-token heal for recurring breaks |
| `DOMSnapshotCascade` | Existing: embed scoring → DOM capture strategy |
| `AiHealer` | Existing: LLM cascade with workflow context |
| `apply_heals()` | CLI function: reads suggestions, diffs, patches workflow JSON |
