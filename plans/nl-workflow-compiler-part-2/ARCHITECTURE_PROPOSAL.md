# NL Workflow Compiler Part 2 — Architecture Proposal

## Problem Statement

Part 1's compile-once takes a single ARIA snapshot at the base URL. For multi-page flows (login → inventory → cart → checkout), the AI infers intermediate pages blind. Locators it generates for pages it never saw are fragile and need healing more often. This part adds a per-page live loop so every page's real DOM drives the step generation for that page.

## Proposed Solution

Three additions, all in the Engine layer — no POM or Glue changes:

1. **`ARIAFilter`** — filters the raw ARIA tree before sending to AI, reducing tokens while keeping relevant nodes
2. **`LiveLoopCompiler`** — per-page compile-execute loop: snapshot → plan → execute → detect navigation → repeat
3. **Enhanced `AiHealer`** — optionally receives full workflow context for smarter recovery

## Engine-Only Architecture

```
No POM or Glue changes.
No new action names.
No new workflow JSON keys.

New Engine files:
  stepper/engine/compiler/aria_filter.py     ← ARIAFilter (3 strategies)
  stepper/engine/compiler/live_loop.py       ← LiveLoopCompiler

Modified Engine files:
  stepper/engine/healer/ai_healer.py        ← heal() gets optional full context
  stepper/main.py                            ← --live flag + live_workflow() function
```

## Key Design Decisions

### Decision 1: LiveLoopCompiler vs. extending NLCompiler
- **Options considered**:
  - A: Add a `mode="live"` parameter to NLCompiler
  - B: Separate `LiveLoopCompiler` class that owns the page-loop logic
- **Chosen**: B
- **Rationale**: NLCompiler's responsibility is "snapshot one page → produce JSON". LiveLoopCompiler's responsibility is "run an agent loop". SRP — they differ in lifecycle, browser ownership, and output format. Extending NLCompiler with mode flags would make both harder to read.

### Decision 2: Navigation detection mechanism
- **Options considered**:
  - A: Poll `page.url()` every 500ms and compare to previous URL
  - B: Listen to `page.on("framenavigated")` event
  - C: Compare ARIA tree hash before/after step execution
- **Chosen**: B (framenavigated event), with C as confirmation
- **Rationale**: `framenavigated` is zero-cost and fires exactly when navigation occurs. Hash comparison catches SPA route changes that don't trigger full navigation. Together they cover both MPA and SPA sites.

### Decision 3: When does the loop end?
- **Options considered**:
  - A: AI returns a special `{"done": true}` step
  - B: AI returns an empty steps array
  - C: Fixed max-pages cap
- **Chosen**: B + C (empty array = done, hard cap at 10 pages as safety net)
- **Rationale**: Asking the model to emit a special token adds prompt complexity. Empty array is natural — "no more steps needed on this page" — and the cap prevents infinite loops.

### Decision 4: ARIAFilter strategy selection
- **Options considered**:
  - A: Always send full tree (simple, expensive on complex pages)
  - B: Always send interactive-only (cheap, may miss context)
  - C: Dynamic selection by node count with fallback
- **Chosen**: C
- **Rationale**: Node count is a cheap proxy for page complexity. ≤50 nodes: full (most context for simple pages). 51–150: interactive-only (focused without landmark noise). 151+: viewport+interactive (densest pages need spatial filtering). Fallback ensures 0-node filter result doesn't break the flow.

### Decision 5: Healer full context — backward compatibility
- **Options considered**:
  - A: New method `heal_with_context()` alongside `heal()`
  - B: Optional keyword args added to existing `heal()` signature
- **Chosen**: B (optional kwargs)
- **Rationale**: `HealerStrategy` ABC has one method. Adding a second breaks the ISP and requires all implementations to add it. Optional kwargs extend naturally — existing callers don't change, new callers opt in.

## ARIA Filtering Design

```python
class ARIAFilter:
    INTERACTIVE_ROLES = {
        "button", "textbox", "link", "combobox",
        "checkbox", "radio", "menuitem", "tab", "option"
    }

    @classmethod
    def select_strategy(cls, node_count: int) -> str:
        if node_count <= 50:   return "full"
        if node_count <= 150:  return "interactive_only"
        return "viewport_interactive"

    @classmethod
    def apply(cls, tree: dict, strategy: str, page=None) -> list[dict]:
        ...
```

## Enhanced Healer Prompt Structure

When full context is provided:
```json
{
  "failed_step": { ... },
  "error": "...",
  "dom": "...",
  "workflow_context": {
    "total_steps": 8,
    "current_index": 5,
    "intent": "log in, add to cart, checkout",
    "nearby_steps": [step4, step5_failed, step6],
    "context_vars": { "username": "standard_user" }
  }
}
```

`nearby_steps` = ±3 steps around current_index to stay within token budget.

## Risks
- **SPA navigation not detected**: Mitigation — ARIA tree hash diff as secondary check
- **AI returns too many steps per page**: Mitigation — cap page steps at 15, log a warning
- **Full context exceeds token limit in healer**: Mitigation — truncate to nearby_steps only (±3), not all_steps
- **Live loop diverges** (AI keeps generating steps on same page): Mitigation — same-URL cycle detection: if URL unchanged after executing a batch, increment stall counter, stop at 3
