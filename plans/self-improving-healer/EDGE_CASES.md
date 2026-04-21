# Self-Improving Healer — Edge Cases

## Category 1: Visual Bridge

### EC-1.1: Element temporarily hidden during page load
- **Trigger**: Page renders slowly; element in DOM but not yet visible when heal fires
- **Expected behavior**: Wait 2s, recheck visibility — if visible after wait, return None (proceed to cascade as normal locator failure, not state failure)
- **Handled in**: Phase 1 — VISIBILITY_WAIT_S delay in VisualBridge.check()

### EC-1.2: bounding_box() returns None despite is_visible() True
- **Trigger**: Element is in shadow DOM or off-screen via CSS transform
- **Expected behavior**: VisualBridge.check() catches exception → returns None → cascade proceeds
- **Handled in**: Phase 1 — try/except wraps entire check body

### EC-1.3: step.element is None or empty
- **Trigger**: Step has no element field (e.g., navigate action misfired)
- **Expected behavior**: _best_locator returns None → check() returns None → cascade proceeds unchanged
- **Handled in**: Phase 1 — None guard in _best_locator

---

## Category 2: Heal Cache

### EC-2.1: Corrupt or missing heal_cache.json
- **Trigger**: File deleted, partial write, or first run ever
- **Expected behavior**: HealCache loads empty dict, logs WARNING if file exists but is corrupt
- **Handled in**: Phase 2 — try/except in HealCache._load()

### EC-2.2: Stale cache entry (element no longer on page)
- **Trigger**: Site redesign removes the healed element entirely; cache still has old healed_cfg
- **Expected behavior**: replacement_runner runs with stale cfg → step fails → log "[HealCache] stale entry — falling through to cascade" → cascade re-heals and overwrites cache entry
- **Handled in**: Phase 2 — replacement failure falls through within heal_attempt loop

### EC-2.3: Cache key collision (sha256[:16] conflict)
- **Trigger**: Two different steps hash to same 16-char prefix (astronomically unlikely)
- **Expected behavior**: Wrong healed_cfg applied → step fails → stale entry path kicks in → re-heals
- **Risk**: Extremely low (1 in 18 trillion). Acceptable without mitigation.

### EC-2.4: Cache grows unboundedly
- **Trigger**: Many different elements healed over months
- **Expected behavior**: No eviction in v1. Cache file stays small (one JSON object per unique broken element). Acceptable — 1000 entries ≈ 50KB.
- **Known limitation**: No TTL or max-size in v1.

---

## Category 3: --apply-heals

### EC-3.1: heal_suggestions.json not found
- **Trigger**: No healing has run yet, or run was in a different working directory
- **Expected behavior**: Print clear error with both expected paths; exit without touching workflow
- **Handled in**: Phase 3 — two-path search with explicit error message

### EC-3.2: Description mismatch (suggestion references renamed step)
- **Trigger**: Workflow was edited between heal run and --apply-heals run
- **Expected behavior**: Warn "no step found with description '...' — skipping"; continue with other suggestions
- **Handled in**: Phase 3 — per-suggestion match check

### EC-3.3: --apply-heals run twice (idempotent)
- **Trigger**: Developer runs --apply-heals again after already applying
- **Expected behavior**: heal_suggestions.json still has same suggestions → AFTER value already matches current element → diff shows no change or applies same value (idempotent JSON overwrite)
- **Handled in**: Phase 3 — patching is an overwrite, not an append; result is identical

### EC-3.4: --apply-heals with --yes in CI on empty suggestions
- **Trigger**: No broken elements in this run, heal_suggestions.json from previous run
- **Expected behavior**: Print "Nothing to apply." and exit cleanly
- **Handled in**: Phase 3 — check suggestions_to_apply == 0 before prompting

## Known Limitations (v1)
- Heal cache has no TTL — stale entries accumulate silently until a step fails
- --apply-heals matches by description only — duplicate descriptions cause ambiguous patches
- Visual bridge uses first matching locator only — compound cfg lists with multiple valid locators may pick the wrong one
