# Self-Improving Healer — User Stories

## Context

The existing healer (DOMSnapshotCascade → AiHealer) fires every time a step fails, regardless of why. It burns AI tokens on transient states (loading spinners, hidden modals) that aren't locator problems. When the same element breaks repeatedly across CI runs, it re-heals from scratch every time — paying the same AI cost over and over. And when healing succeeds, the fix lives only in `heal_suggestions.json` — it never flows back into the workflow file, so the next human has to apply it manually.

These three upgrades close those gaps: stop healing what doesn't need healing, remember what was already healed, and give the human a single command to make fixes permanent.

---

## Stories

### Story 1.1: Visual bridge — don't heal hidden/disabled elements
**As a** CI operator, **I want** the healer to check if an element is visible and enabled before triggering the cascade, **so that** transient UI states (loading spinners, modals, disabled buttons) don't waste AI tokens on a problem that isn't a locator failure.

**Acceptance Criteria:**
- [ ] Before `DOMSnapshotCascade.capture()`, attempt to locate element using best cfg key
- [ ] If element found but `is_visible()` is False: wait 2s and retry once; if still hidden → fail with `"element found but not visible — possible state/timing issue"`
- [ ] If element found but `is_enabled()` is False: fail immediately with `"element found but disabled — check flow state"`
- [ ] If element not found at all → proceed to DOMSnapshotCascade as before
- [ ] All checks logged at DEBUG; visible path logged at INFO

**Edge Cases:**
- Element becomes visible during the 2s wait → proceed normally without triggering healer
- `bounding_box()` returns None even though `is_visible()` is True → treat as not found, proceed to cascade

### Story 1.2: Local heal cache — zero tokens for recurring breaks
**As a** QA engineer running 100 CI runs/day, **I want** healed element fixes to be remembered across runs, **so that** the same broken locator is only healed by AI once and applied for free on every subsequent run.

**Acceptance Criteria:**
- [ ] `HealCache` class in `stepper/engine/healer/healing_cache.py`
- [ ] Cache stored as `stepper/sites/<site>/artifacts/heal_cache.json` (one per site)
- [ ] Cache key: `sha256(action + "|" + description + "|" + json(original_element))[:16]`
- [ ] On step failure: check cache before DOMSnapshotCascade — cache hit applies healed cfg directly (0 tokens)
- [ ] On successful AI heal: write entry to cache automatically
- [ ] Cache loaded once at StepRunner construction; written atomically on each new heal
- [ ] Log `"[HealCache] HIT — skipping cascade"` or `"[HealCache] MISS — proceeding to cascade"`

**Edge Cases:**
- Cache file missing or corrupt JSON → start with empty cache, log WARNING
- Cache hit but healed element no longer exists on page → fall through to cascade (stale entry)

### Story 1.3: --apply-heals — human-in-the-loop write-back
**As a** developer, **I want** a CLI command that reads `heal_suggestions.json` and surgically patches the source workflow JSON, **so that** healed fixes become permanent after I review and approve them — making the framework self-improving with human oversight.

**Acceptance Criteria:**
- [ ] `python stepper/main.py --apply-heals <workflow.json>` reads `heal_suggestions.json` from the workflow's sibling `artifacts/` dir
- [ ] Shows human-readable diff per step: `step N "<description>": css: .old-selector → role: button name: "Submit"`
- [ ] Asks for confirmation before patching (default: yes with `--yes` flag for CI)
- [ ] Patches the `element` field in the matching workflow JSON step in-place
- [ ] Prints: `"N heals applied to <workflow.json>. Commit to make permanent."`
- [ ] If no heal_suggestions.json found: clear error with expected path

**Edge Cases:**
- Step description in suggestions doesn't match any step in workflow → warn, skip that suggestion
- Workflow JSON has multiple steps with same description → patch all matching (warn about ambiguity)
- --apply-heals on a workflow that has already been patched (same suggestion twice) → idempotent, no double-patch
