# NL Workflow Compiler — Architecture Proposal

## Problem Statement

Writing workflow JSON requires knowing action names, parameter shapes, and cfg list conventions. This is a barrier for new automation authors and slows iteration. We want to let users write plain English and get a runnable workflow file — paying AI tokens once, then executing deterministically forever after.

## Proposed Solution

A **compile** mode added to `stepper/main.py`. The compiler:
1. Opens a headless browser and navigates to the site's base URL
2. Takes a lightweight ARIA accessibility tree snapshot (`page.accessibility.snapshot()`)
3. Extracts the action registry schema via the existing `ActionSchemaExtractor`
4. Sends intent + ARIA tree + action schema to AI (Groq → Gemini → Claude via AIService)
5. Parses the JSON response into a standard workflow file
6. Saves to `stepper/sites/<site>/workflows/`

Execution from that point is 100% deterministic — existing runner, resolver cascade, self-healing.

## Three-Layer Impact

```
No new POM or Glue layer changes needed.
The compiler lives entirely in the Engine layer.

Engine layer additions:
  stepper/engine/compiler/
    compiler.py        ← NLCompiler class (orchestration)
    prompt_builder.py  ← builds system + user prompts
    output_parser.py   ← parses + validates AI JSON response

AIService addition:
  "compile" task type  ← Groq → Gemini → Claude, 3000 tokens out

main.py addition:
  --compile "intent"   ← new CLI flag
  --site <name>        ← which site's base URL and workflows/ folder
  --output <path>      ← optional override for output path
```

## Key Design Decisions

### Decision 1: New `compile` task type in AIService vs. direct provider call
- **Options considered**:
  - A: Hardcode Claude call in compiler (like `ClaudePlanner` does today)
  - B: Add `"compile"` task type to `AIService` provider chain
- **Chosen**: B
- **Rationale**: AIService already handles Groq → Gemini → Claude fallback with logging. Adding a new task type is 3 lines. Option A duplicates provider logic and skips Groq entirely (more expensive).

### Decision 2: ARIA tree vs. full DOM vs. screenshot
- **Options considered**:
  - A: Full DOM snapshot (innerHTML) — complete but huge (~50K tokens)
  - B: Visual screenshot → AI identifies elements — expensive, no structured output
  - C: `page.accessibility.snapshot()` — compact, role/name/label already structured
- **Chosen**: C
- **Rationale**: ARIA tree tokens are ~50 per node vs ~2000 for a screenshot region. The snapshot already contains `role`, `name`, `label` — exactly the cfg keys the resolver prefers. Deterministic strategies (RoleResolver, LabelResolver) are higher priority than CSS/XPath, so ARIA-sourced selectors heal better.

### Decision 3: Where compiler navigates (base URL vs. specific page)
- **Options considered**:
  - A: Only snapshot base URL → AI infers page flow
  - B: Snapshot each step's destination URL (multi-page compile)
  - C: Base URL snapshot + user describes multi-step intent → AI fills in navigation
- **Chosen**: A for v1 (single snapshot)
- **Rationale**: Multi-page snapshot requires a full agent loop — adds complexity. Single snapshot with good intent description produces correct `navigate` steps for intermediate pages. Self-healing corrects any locator drift. Can upgrade to B in a later plan.

### Decision 4: Output file naming
- **Options considered**:
  - A: Timestamp-based (`compiled_20260421_143200.json`)
  - B: AI-suggested name derived from intent
  - C: User provides `--output` flag, default to `compiled.json`
- **Chosen**: C — explicit `--output` with a safe default
- **Rationale**: Predictable, no ambiguity, easy to pipe into `--workflow`.

## New Action Names
No new action names. Compiler reuses the existing registered actions.

## cfg List Design (AI prompt guidance)
The system prompt instructs the AI:
- Prefer `role` + `name` (priority 10) — matches ARIA tree directly
- Use `label` (priority 20) for inputs
- Use `placeholder` (priority 30) for text inputs without labels
- Use `id` (priority 50) when role/label absent
- Use `css` (priority 60) only as last resort
- Always include at least 2 fallback strategies per element
- Always set explicit `"priority"` values

## Risks
- **ARIA tree too large**: Mitigation — truncate at 200 nodes with a warning log
- **AI generates unknown action names**: Mitigation — `output_parser.py` validates each action name against the registry; invalid steps are flagged, not silently dropped
- **Site requires login before ARIA tree is useful**: Mitigation — compiler accepts `--compile-after-login` flag (v2); v1 documents this limitation
