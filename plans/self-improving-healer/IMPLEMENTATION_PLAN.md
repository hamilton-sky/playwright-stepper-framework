# Self-Improving Healer — Implementation Plan

## Overview

Three engine-only upgrades to the healing subsystem. No POM, Glue, or workflow JSON changes. Each phase is independent — they stack on top of each other but each can be verified alone.

## Layer Architecture

```
Engine layer only:
  stepper/engine/healer/visual_bridge.py   ← NEW (Phase 1)
  stepper/engine/healer/healing_cache.py   ← NEW (Phase 2)
  stepper/engine/runner/step_runner.py     ← modified (Phases 1+2)
  stepper/main.py                          ← modified (Phase 3)
```

---

## Phase 1: Visual Bridge
**Layer:** Engine
**Files:**
- `stepper/engine/healer/visual_bridge.py` — NEW: `VisualBridge` class
- `stepper/engine/runner/step_runner.py` — add visual bridge call before DOMSnapshotCascade

**Details:**

```python
class VisualBridge:
    VISIBILITY_WAIT_S = 2.0

    @staticmethod
    def _best_locator(page, step: StepConfig):
        """Try to locate element using the best available cfg key. Returns locator or None."""
        el = step.element or {}
        if el.get("role") and el.get("name"):
            return page.get_by_role(el["role"], name=el["name"]).first
        if el.get("label"):
            return page.get_by_label(el["label"]).first
        if el.get("placeholder"):
            return page.get_by_placeholder(el["placeholder"]).first
        if el.get("id"):
            return page.locator(f"#{el['id']}").first
        if el.get("css"):
            return page.locator(el["css"]).first
        return None

    @classmethod
    async def check(cls, page, step: StepConfig) -> str | None:
        """
        Returns:
          None          → element not found at all → proceed to cascade
          "hidden"      → element found but not visible after wait
          "disabled"    → element found but not enabled
          "ok"          → element found, visible, enabled (rare — resolver should have caught it)
        """
        locator = cls._best_locator(page, step)
        if locator is None:
            return None
        try:
            count = await locator.count()
            if count == 0:
                return None
            visible = await locator.first.is_visible()
            if not visible:
                await asyncio.sleep(cls.VISIBILITY_WAIT_S)
                visible = await locator.first.is_visible()
                if not visible:
                    return "hidden"
            enabled = await locator.first.is_enabled()
            if not enabled:
                return "disabled"
            return "ok"
        except Exception:
            return None  # unknown state → let cascade decide
```

In `StepRunner` heal loop, add before `DOMSnapshotCascade.capture()`:
```python
bridge_result = await VisualBridge.check(self._page, step)
if bridge_result == "hidden":
    result = StepResult(step=step, status="failed",
        error="element found but not visible — possible state/timing issue (visual bridge)")
    break  # exit heal loop, do not call AI
if bridge_result == "disabled":
    result = StepResult(step=step, status="failed",
        error="element found but disabled — check flow state (visual bridge)")
    break
# None or "ok" → proceed to DOMSnapshotCascade
```

**Verify:**
```bash
python -c "from engine.healer.visual_bridge import VisualBridge; print('ok')"
python stepper/main.py --workflow stepper/sites/saucedemo/workflows/checkout.json --show --heal 1
# Should run without regression; hidden elements now fail fast with clear message
```

---

## Phase 2: Local Heal Cache
**Layer:** Engine
**Files:**
- `stepper/engine/healer/healing_cache.py` — NEW: `HealCache` class
- `stepper/engine/runner/step_runner.py` — add cache check + cache write into heal loop

**Details:**

```python
import hashlib, json
from pathlib import Path

class HealCache:
    def __init__(self, cache_path: Path):
        self._path = cache_path
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if self._path.exists():
                logger.warning(f"[HealCache] corrupt cache at {self._path} — starting fresh: {e}")
            return {}

    @staticmethod
    def make_key(step) -> str:
        raw = f"{step.action}|{step.description or ''}|{json.dumps(step.element or {}, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, step) -> dict | None:
        return self._data.get(self.make_key(step))

    def put(self, step, healed_cfg: dict) -> None:
        self._data[self.make_key(step)] = healed_cfg
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
```

Cache path resolution: in `StepRunner.__init__`, accept optional `cache_path: Path | None = None`. In `main.py`, derive from workflow path: `stepper/sites/<site>/artifacts/heal_cache.json`.

In `StepRunner` heal loop, add before `VisualBridge.check()`:
```python
if self._cache:
    cached_cfg = self._cache.get(step)
    if cached_cfg:
        logger.info(f"[HealCache] HIT for '{step.action}' — skipping cascade")
        replacement_steps = [self._healer._apply_healed_cfg(step, cached_cfg)]
        # run replacements as normal...
        # if still fails: log "[HealCache] stale entry" and fall through
```

After successful AI heal, write to cache:
```python
if self._cache and healed_cfg:
    self._cache.put(step, healed_cfg)
```

**Verify:**
```bash
python -c "from engine.healer.healing_cache import HealCache; print('ok')"
# Run a workflow twice with --heal 1:
# First run: cache MISS → AI heals → cache written
# Second run: cache HIT → 0 AI tokens
```

---

## Phase 3: --apply-heals CLI command
**Layer:** Engine / CLI
**Files:**
- `stepper/main.py` — add `--apply-heals` flag + `apply_heals()` function

**Details:**

```
python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json
python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json --yes
```

`apply_heals(workflow_path, auto_yes=False)`:
1. Derive suggestions path: `workflow_path.parent.parent / "artifacts" / "heal_suggestions.json"`
   - If not found: check `screenshots_dir/../heal_suggestions.json` (fallback)
   - If still not found: print error with expected path, exit
2. Load `heal_suggestions.json` → list of `{step, description, action, original, healed}`
3. Load workflow JSON → list of steps
4. For each suggestion: find matching step by `description` field
   - No match → warn `"No step found with description '<desc>' — skipping"`
   - Multiple matches → warn `"Ambiguous — patching all N matches"`
5. Print diff block:
   ```
   Step 4 "click checkout button":
     BEFORE: {"css": ".btn-checkout"}
     AFTER:  {"role": "button", "name": "Checkout", "priority": 0}
   ```
6. If not `--yes`: prompt `"Apply N heals to <workflow>? [Y/n]"`
7. Patch each matched step's `element` field in-place
8. Write updated workflow JSON back to file (preserve formatting with `indent=2`)
9. Print: `"N heals applied to <workflow>. Commit to make permanent."`

**Verify:**
```bash
# 1. Run a workflow with a broken locator + --heal 1 to generate heal_suggestions.json
# 2. Then:
python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json
# Should show diff and prompt
python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json --yes
# Should patch silently
```

---

## Prerequisites
- Existing `AiHealer`, `DOMSnapshotCascade`, `StepRunner`, `HealAnnotator` all work
- `heal_suggestions.json` already written by `StepRunner` (exists)
- No dependency on nl-workflow-compiler plans

## Key Decisions
- Visual bridge in StepRunner (not inside DOMSnapshotCascade) — SRP
- Cache per site in `artifacts/` — matches existing storage_state.json pattern
- `--apply-heals` requires workflow path — unambiguous about which file to patch
- `--yes` flag enables CI automation without interactive prompt
