# NL Workflow Compiler Part 2 — Edge Cases

## Category 1: Navigation Detection

### EC-1.1: SPA route change not detected by framenavigated
- **Trigger**: React/Vue router changes URL hash or history.pushState without full navigation
- **Current behavior**: framenavigated doesn't fire → stall counter increments
- **Expected behavior**: ARIA tree hash diff as secondary check — if tree changed significantly, treat as new page
- **Handled in**: Phase 2 — LiveLoopCompiler._has_page_changed() hash comparison

### EC-1.2: Navigation fires during AI call (race condition)
- **Trigger**: A step triggers navigation before StepRunner finishes the batch
- **Expected behavior**: _navigated flag set to True; loop detects it after current batch completes and continues
- **Handled in**: Phase 2 — flag is set async, checked after runner.run() returns

### EC-1.3: Same URL after execution (stall)
- **Trigger**: AI generates steps that don't trigger navigation (e.g., hover, scroll)
- **Expected behavior**: stall_count increments; after STALL_THRESHOLD (3) → break loop with warning
- **Handled in**: Phase 2 — stall counter logic

## Category 2: ARIA Filter Issues

### EC-2.1: No interactive nodes found after filtering
- **Trigger**: Page is mostly static (e.g., a confirmation screen with just text)
- **Expected behavior**: Fall back to "full" strategy with WARNING log; AI will return [] (done)
- **Handled in**: Phase 1 — ARIAFilter.apply() empty-result fallback

### EC-2.2: Viewport bounding box check fails
- **Trigger**: Playwright evaluate() throws (page context destroyed during navigation)
- **Expected behavior**: Fall back to "interactive_only" with DEBUG log
- **Handled in**: Phase 1 — try/except around evaluate() in viewport_interactive strategy

### EC-2.3: 151+ nodes after interactive filter (dense page)
- **Trigger**: Complex dashboards or pages with many buttons
- **Expected behavior**: viewport_interactive applied; if still >100 nodes, log count for token audit
- **Handled in**: Phase 1 — strategy selection logic

## Category 3: Live Loop Termination

### EC-3.1: Loop exceeds MAX_PAGE_CYCLES (10)
- **Trigger**: Intent is ambiguous or site has infinite scroll
- **Expected behavior**: Loop breaks, saves partial steps with WARNING: "live loop hit page cap (10)"
- **Handled in**: Phase 2 — cycle counter check

### EC-3.2: AI returns more than MAX_STEPS_PER_PAGE (15)
- **Trigger**: AI over-generates (very detailed intent on a complex page)
- **Expected behavior**: Truncate to 15 steps, log WARNING with count
- **Handled in**: Phase 2 — step cap after OutputParser

### EC-3.3: Error mid-loop (step execution fails, no heal)
- **Trigger**: Step fails with healing disabled or healing exhausted
- **Expected behavior**: Save partial steps to `live_<timestamp>_partial.json`, re-raise error with path in message
- **Handled in**: Phase 2 — try/except in LiveLoopCompiler.run()

## Category 4: Enhanced Healer Context

### EC-4.1: Full context pushes prompt over token limit
- **Trigger**: Very long workflow (20+ steps) + large DOM snapshot
- **Expected behavior**: Truncate to nearby_steps (±3 around current_index) only — not all_steps
- **Handled in**: Phase 3 — nearby_steps slicing in AiHealer.heal()

### EC-4.2: Caller passes all_steps but not current_index
- **Trigger**: Partial wiring in a call site
- **Expected behavior**: Skip nearby_steps extraction, include full all_steps (up to 10) with WARNING
- **Handled in**: Phase 3 — guard in AiHealer.heal()

## Known Limitations (v2)
- viewport_interactive bounding box check requires an extra page.evaluate() call per node — may be slow on 150+ node pages
- Live loop does not support parallel page execution (one page at a time)
- Auto-save JSON uses the step dicts as planned per-page; if healing modified steps at runtime, the saved JSON reflects the original plan (not the healed version) — healed steps are logged but not persisted back
