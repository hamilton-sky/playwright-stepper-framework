# NL Workflow Compiler Part 2 — Flow Diagram

## Live Loop Happy Path (--live mode)

```
CLI: python stepper/main.py --live "intent" --site saucedemo
        │
        ▼
live_workflow(args)  [main.py]
        │  build_default_registry() + register_all_sites()
        │  SITE_CONFIGS → base_url
        │
        ▼
LiveLoopCompiler.run(intent, base_url, output_path)
        │
        │  page.on("framenavigated") → _navigated = True
        │  page.goto(base_url)
        │
        └─ LOOP (max 10 cycles):
                │
                ├─ page.accessibility.snapshot() → raw_tree
                │
                ├─ ARIAFilter.count_nodes(raw_tree)
                │       ≤50  → strategy: "full"
                │       ≤150 → strategy: "interactive_only"
                │       151+ → strategy: "viewport_interactive"
                │
                ├─ ARIAFilter.apply(raw_tree, strategy, page)
                │       └─ empty result? → fallback to "full" + WARN
                │
                ├─ PromptBuilder.build(intent, filtered_nodes,
                │                      action_schema, completed_summary)
                │
                ├─ AIService.chat(task_type="compile")
                │       GroqProvider  ──► success → steps
                │       GeminiProvider ─► fallback
                │       ClaudeProvider ─► last resort
                │
                ├─ OutputParser.parse(raw) → page_steps
                │       └─ empty? → BREAK (intent complete)
                │
                ├─ [cap page_steps at 15]
                │
                ├─ _navigated = False
                │
                ├─ StepRunner.run(page_steps)
                │       │  for each step:
                │       │  ElementResolver cascade (no AI normally)
                │       │       └─ fail → AiHealer.heal(
                │       │                   step, error, dom,
                │       │                   all_steps=all_steps,
                │       │                   current_index=i,
                │       │                   completed_steps=results[:i])
                │       └─ results collected
                │
                ├─ wait 2s for _navigated flag
                │       _navigated=True  → new page → continue loop
                │       _navigated=False → same URL:
                │               stall_count += 1
                │               stall_count ≥ 3 → BREAK + WARN
                │
                └─ all_steps.extend(page_steps)

        │  write all_steps → live_<timestamp>.json
        │
        ▼
"Workflow saved to: stepper/sites/saucedemo/workflows/live_*.json"
"Run deterministically: python stepper/main.py --workflow <path>"
```

---

## ARIA Filter Decision Tree

```
page.accessibility.snapshot() → raw_tree
        │
        ▼
ARIAFilter.count_nodes(raw_tree)
        │
        ├─ ≤50   → "full"
        │           serialize entire tree → compact JSON
        │
        ├─ ≤150  → "interactive_only"
        │           walk tree, keep role ∈ INTERACTIVE_ROLES
        │           include name/label/placeholder/value
        │
        └─ 151+  → "viewport_interactive"
                    interactive_only
                        ↓
                    page.evaluate() bounding box per node
                        │
                        ├─ evaluate fails → fallback: "interactive_only"
                        └─ filter: keep nodes within viewport bounds

        └─ (any strategy) result empty?
                → fallback: "full" + WARNING log
```

---

## Enhanced AiHealer Context Flow

```
StepRunner: step i fails
        │
        ▼
AiHealer.heal(
    step=failed_step,
    error=error_msg,
    dom=dom_payload,        ← existing (DOMSnapshotCascade output)
    all_steps=all_steps,    ← NEW optional (for nearby_steps extraction)
    current_index=i,        ← NEW optional
    context_vars=context,   ← NEW optional
    # aria_snapshot NOT added — dom.content already covers this
)
        │
        ├─ fast path: dom.healed_cfg is not None
        │       → apply healed cfg directly (0 AI tokens)
        │
        └─ slow path: build user_msg JSON
                {
                  "failed_step": {...},
                  "error": "...",
                  "dom": "...",
                  "workflow_context": {              ← NEW when provided
                    "total_steps": N,
                    "current_index": i,
                    "nearby_steps": [i-3..i+3],    ← ±3, action+desc only
                    "context_vars": {...}            ← stored run vars
                  }
                  // NO aria_snapshot — dom.content covers it already
                }
                        │
                        ▼
                AIService.chat(task_type="heal")
                Groq → Gemini → Claude
```

---

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `LiveLoopCompiler` | Owns browser lifecycle, per-page loop orchestration |
| `ARIAFilter` | Filters ARIA tree by strategy; reduces token cost |
| `PromptBuilder` | Assembles AI prompt (reused from Part 1) |
| `OutputParser` | Parses + validates AI JSON (reused from Part 1) |
| `StepRunner` | Executes one page's steps (existing, unchanged interface) |
| `AiHealer` | Heals broken steps; now optionally receives full workflow context |
| `_navigated flag` | Set by framenavigated event; signals when to re-snapshot |
