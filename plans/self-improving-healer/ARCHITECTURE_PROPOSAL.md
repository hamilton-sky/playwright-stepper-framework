# Self-Improving Healer — Architecture Proposal

## Problem Statement

The healer fires on every step failure regardless of cause, pays AI tokens for recurring breaks, and never writes fixes back to the source. Three targeted upgrades close these gaps with minimal code and zero POM/Glue changes.

## Proposed Solution

```
Step fails
    │
    ▼  Phase 1: Visual Bridge (NEW)
    ├─ locate element with best cfg key (try_locate)
    │       found + not visible → wait 2s + retry → fail as state error (no AI)
    │       found + not enabled → fail as state error (no AI)
    │       not found → continue to cascade
    │
    ▼  Phase 2: HealCache lookup (NEW)
    ├─ key = sha256(action|description|original_element)[:16]
    │       HIT  → apply healed_cfg directly (0 tokens, 0 AI)
    │       MISS → continue to DOMSnapshotCascade
    │
    ▼  Existing: DOMSnapshotCascade → AiHealer (unchanged)
    │       on success → write to HealCache + heal_suggestions.json
    │
    ▼  Phase 3: --apply-heals (NEW, separate CLI command)
        reads heal_suggestions.json
        shows diff → human approves → patches workflow JSON
```

## Engine-Only Architecture

```
No POM, Glue, or workflow JSON changes.

New Engine files:
  stepper/engine/healer/healing_cache.py   ← HealCache class
  stepper/engine/healer/visual_bridge.py   ← VisualBridge class

Modified Engine files:
  stepper/engine/runner/step_runner.py     ← wire visual bridge + cache into heal loop
  stepper/main.py                          ← --apply-heals flag + apply_heals() function
```

## Key Design Decisions

### Decision 1: Visual bridge location — before or inside DOMSnapshotCascade?
- **Options**:
  - A: Inside `DOMSnapshotCascade.capture()` as a pre-check
  - B: In `StepRunner` before calling `DOMSnapshotCascade.capture()`
- **Chosen**: B — in StepRunner
- **Rationale**: SRP — DOMSnapshotCascade's job is DOM inspection, not flow control. StepRunner already owns the heal decision logic. The visual check is a "should we even heal?" gate, not a "how do we snapshot?" decision.

### Decision 2: Cache key design
- **Options**:
  - A: Full element cfg JSON as key (long, brittle to whitespace)
  - B: `sha256(action + "|" + description + "|" + sorted_json(original_element))[:16]`
  - C: Step index (breaks when workflow changes)
- **Chosen**: B
- **Rationale**: Stable across runs even if workflow reorders. Sorted JSON prevents key mismatch from dict ordering. 16-char prefix eliminates collisions in practice while staying readable.

### Decision 3: Cache storage location
- **Options**:
  - A: One global cache file for all sites
  - B: Per-site `artifacts/heal_cache.json`
  - C: Per-workflow cache file
- **Chosen**: B
- **Rationale**: Sites have different elements — cross-site contamination would be wrong. Per-workflow is too granular (same element appears in multiple workflows). Per-site matches the existing `artifacts/` pattern (storage_state.json lives there too).

### Decision 4: --apply-heals confirmation UX
- **Options**:
  - A: Auto-apply silently
  - B: Show diff + prompt Y/N per suggestion
  - C: Show all diffs then single Y/N
- **Chosen**: C with `--yes` flag for CI bypass
- **Rationale**: Human reviews all changes as a batch before committing. `--yes` allows CI pipelines to auto-apply after a review gate. Option B is tedious for many suggestions.

### Decision 5: Cache hit with stale entry (element no longer on page)
- **Options**:
  - A: Trust cache unconditionally — fastest
  - B: Verify healed_cfg still resolves before applying — safe but adds a locator call
  - C: Apply from cache; if step still fails, fall through to cascade (invalidate entry)
- **Chosen**: C
- **Rationale**: Cache hit failure is rare. Paying a locator check on every cache hit slows the common path. Letting the step fail and re-cascade naturally handles stale entries without special logic.

## Risks
- **Visual bridge false-positive on slow pages**: element temporarily hidden during load → 2s wait mitigates most cases; remaining misses fall through to cascade
- **Cache poisoning**: bad healed_cfg written to cache after a fluke heal → stale entry detected by Option C above (step fails → cascade → overwrites)
- **--apply-heals on wrong workflow**: heal_suggestions.json may reference steps from a different workflow → description mismatch check catches this; warns and skips
