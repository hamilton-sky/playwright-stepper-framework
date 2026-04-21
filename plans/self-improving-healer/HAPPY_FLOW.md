# Self-Improving Healer — Happy Flow

## Overview

A SauceDemo checkout workflow has a stale CSS selector after a site update. The first CI run heals it via AI, caches the fix, and writes a suggestion. A developer runs `--apply-heals` to make it permanent. Every run after that is free.

---

## Run 1 — First failure, AI heals, cache written

### Step 1: Workflow runs, locator fails
- **Stepper does**: `sd_checkout` step fires → resolver can't find `.btn-checkout` (site changed)
- **Result**: step fails → heal loop triggers

### Step 2: Visual bridge check
- **Stepper does**: `VisualBridge.check()` — tries to find element with best cfg key
- **Result**: count == 0 → element not found → returns `None` → proceed (not a visibility issue)

### Step 3: Heal cache miss
- **Stepper does**: `HealCache.get(step)` → key not in cache
- **Log**: `[HealCache] MISS — proceeding to cascade`

### Step 4: DOMSnapshotCascade
- **Stepper does**: cosine similarity scoring against live DOM — score 0.62 → scoped DOM strategy
- **Result**: `DomPayload(strategy_used="scoped", ~100 tokens)`

### Step 5: AiHealer (Groq)
- **Stepper does**: sends failed_step + dom + workflow_context (nearby steps) → Groq responds
- **Result**: `[{"action":"sd_checkout","element":{"role":"button","name":"Checkout",...}}]`

### Step 6: Healed step runs + cache written
- **Stepper does**: runs replacement step → succeeds → `HealCache.put(step, healed_cfg)`
- **Files written**: `artifacts/heal_cache.json`, `artifacts/heal_suggestions.json`
- **Log**: `⚕ Step 5 healed on attempt 1`

---

## Developer reviews and applies fix

### Step 7: Developer runs --apply-heals
```bash
python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json
```
- **Output**:
  ```
  Step 5 "complete checkout":
    BEFORE: {"css": ".btn-checkout"}
    AFTER:  {"role": "button", "name": "Checkout", "priority": 0}

  Apply 1 heal to checkout.json? [Y/n]: Y
  1 heal(s) applied to checkout.json. Commit to make permanent.
  ```

### Step 8: Developer commits updated workflow
- `git add stepper/sites/saucedemo/workflows/checkout.json`
- `git commit -m "apply healed selector for checkout button"`

---

## Run 2+ — Cache hit, zero AI tokens

### Step 9: Same workflow runs again
- **Stepper does**: step fails (old selector still in source until commit lands) OR runs fine if commit landed
- **Heal cache**: `HealCache.get(step)` → HIT → apply healed_cfg directly
- **Log**: `⚕ [HealCache] HIT for 'sd_checkout' — skipping cascade`
- **AI tokens**: 0

---

## Success Indicators
- [ ] Run 1: step healed by AI, `heal_cache.json` written, `heal_suggestions.json` updated
- [ ] Run 2: `[HealCache] HIT` in logs, no AI provider called
- [ ] `--apply-heals` patches the correct step in workflow JSON
- [ ] Patched workflow passes on next run without healing
- [ ] Exam tests unaffected throughout
