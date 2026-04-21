# Self-Improving Healer — Conversation Guide

Split into 3 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: Visual Bridge (Phase 1)

**Prompt to paste:**
```
Implement Self-Improving Healer Conversation 1 (Phase 1) from plans/self-improving-healer/IMPLEMENTATION_PLAN.md.

Scope — Phase 1: Visual Bridge

Create stepper/engine/healer/visual_bridge.py with VisualBridge class:
- Static method _best_locator(page, step) → Playwright locator or None
  Try keys in priority order: role+name, label, placeholder, id, css
  Return page.get_by_role/get_by_label/get_by_placeholder/locator as appropriate
  Return None if step.element is empty or has no recognised key
- Class method async check(page, step) -> str | None
  Returns: None (not found → proceed to cascade), "hidden", "disabled", "ok"
  If locator is None → return None
  If locator.count() == 0 → return None
  If not is_visible(): wait VISIBILITY_WAIT_S (2.0s) then recheck
    still not visible → return "hidden"
  If not is_enabled() → return "disabled"
  Otherwise → return "ok"
  Wrap entire body in try/except Exception → return None on any error

Modify stepper/engine/runner/step_runner.py:
- Import VisualBridge at top of file
- In the heal loop (inside the while heal_attempt < self._max_heal_attempts block),
  add BEFORE the DOMSnapshotCascade.capture() call:
    bridge_result = await VisualBridge.check(self._page, step)
    if bridge_result == "hidden":
        result = dataclasses.replace(result, status="failed",
            error="element found but not visible — state/timing issue (visual bridge)")
        self._notify_log("⚕ Visual bridge: element hidden — skipping healer", "warning")
        break  # exit heal loop, no AI call
    if bridge_result == "disabled":
        result = dataclasses.replace(result, status="failed",
            error="element found but disabled — check flow state (visual bridge)")
        self._notify_log("⚕ Visual bridge: element disabled — skipping healer", "warning")
        break

Do NOT touch healing_cache.py, ai_healer.py, dom_snapshot.py, main.py, or any POM/Glue files.
Do NOT change the DOMSnapshotCascade call or the AiHealer call — only add the bridge before them.
All existing exam tests must still pass: pytest exam/ -x -q

Verify:
  python -c "from engine.healer.visual_bridge import VisualBridge; print('ok')"
  pytest exam/ -x -q

After done, update plans/self-improving-healer/PROGRESS.md phase 1 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** VisualBridge importable; StepRunner heal loop has bridge check before cascade; existing tests pass.
**Files touched:** `stepper/engine/healer/visual_bridge.py` (NEW), `stepper/engine/runner/step_runner.py`

---

## Conversation 2: Local Heal Cache (Phase 2)

**Prompt to paste:**
```
Implement Self-Improving Healer Conversation 2 (Phase 2) from plans/self-improving-healer/IMPLEMENTATION_PLAN.md.
Conversation 1 is DONE: VisualBridge exists and is wired into StepRunner.

Scope — Phase 2: Local Heal Cache

Create stepper/engine/healer/healing_cache.py with HealCache class:
- __init__(self, cache_path: Path): load existing JSON or start empty dict
  On corrupt JSON: log WARNING, start empty (do not raise)
- Static method make_key(step) -> str:
  raw = f"{step.action}|{step.description or ''}|{json.dumps(step.element or {}, sort_keys=True)}"
  return hashlib.sha256(raw.encode()).hexdigest()[:16]
- get(self, step) -> dict | None: return self._data.get(make_key(step))
- put(self, step, healed_cfg: dict) -> None:
  Store in _data, write atomically to _path (mkdir parents if needed)
  Log: "[HealCache] wrote entry for '<step.action>'"

Modify stepper/engine/runner/step_runner.py:
- Add optional _cache: HealCache | None = None to StepRunner.__init__() (default None)
- In the heal loop, add BEFORE the VisualBridge.check() call:
    if self._cache:
        cached_cfg = self._cache.get(step)
        if cached_cfg is not None:
            self._notify_log(f"⚕ [HealCache] HIT for '{step.action}' — skipping cascade", "warning")
            replacement_steps = [self._healer._apply_healed_cfg(step, cached_cfg)]
            # run replacement_runner as normal (existing code)
            # if replacement still fails: log "[HealCache] stale entry — falling through to cascade"
            # and continue the heal_attempt loop (do not break)
- After a successful AI heal (where healed_cfg is set), add:
    if self._cache and healed_cfg:
        self._cache.put(step, healed_cfg)

Modify stepper/main.py:
- In run() function, when building StepRunner, derive cache_path from workflow_path:
  If workflow_path is set:
    parts = Path(workflow_path).parts
    find "sites" in parts → cache_path = stepper_root / "sites" / site_name / "artifacts" / "heal_cache.json"
  Pass cache_path to HealCache(cache_path) and inject into StepRunner as _cache
  If workflow_path is None (task mode): no cache

Do NOT touch visual_bridge.py, ai_healer.py, dom_snapshot.py, or any POM/Glue files.
All existing exam tests must still pass: pytest exam/ -x -q

Verify:
  python -c "from engine.healer.healing_cache import HealCache; print('ok')"
  # Run a workflow with a deliberately broken locator + --heal 1 twice:
  # First run: "[HealCache] MISS" in logs → AI heals → cache written
  # Second run: "[HealCache] HIT" in logs → no AI call
  pytest exam/ -x -q

After done, update plans/self-improving-healer/PROGRESS.md phase 2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** HealCache importable; second run of same broken workflow hits cache with 0 AI tokens; exam tests pass.
**Files touched:** `stepper/engine/healer/healing_cache.py` (NEW), `stepper/engine/runner/step_runner.py`, `stepper/main.py`

---

## Conversation 3: --apply-heals CLI (Phase 3)

**Prompt to paste:**
```
Implement Self-Improving Healer Conversation 3 (Phase 3) from plans/self-improving-healer/IMPLEMENTATION_PLAN.md.
Conversations 1–2 are DONE: VisualBridge and HealCache exist and are wired.

Scope — Phase 3: --apply-heals CLI command

Modify stepper/main.py:
1. Add argparse argument --apply-heals TEXT (metavar="WORKFLOW_JSON",
   help="Apply heal_suggestions.json fixes to the given workflow file")
2. Add argparse flag --yes (action="store_true",
   help="Auto-confirm --apply-heals without interactive prompt")
3. --apply-heals is mutually exclusive with --workflow, --task, --compile, --live
   (add check at top of main(), raise parser.error if combined)

Add function apply_heals(workflow_path: Path, auto_yes: bool) in main.py:
1. Derive suggestions path:
   Try: workflow_path.parent.parent / "artifacts" / "heal_suggestions.json"
   Fallback: workflow_path.parent / "artifacts" / "heal_suggestions.json"
   If neither exists: print error with both expected paths, return
2. Load suggestions (list of dicts with keys: step, description, action, original, healed)
3. Load workflow JSON (handle both list-of-steps and {"steps": [...]} formats)
4. For each suggestion:
   Find steps where step["description"] == suggestion["description"]
   No match → print f"WARNING: no step found with description '{desc}' — skipping"
   Multiple → print f"WARNING: {n} steps match '{desc}' — patching all"
5. Print diff for all suggestions:
   f"Step {n} \"{desc}\":\n  BEFORE: {json.dumps(original)}\n  AFTER:  {json.dumps(healed)}"
6. If suggestions_to_apply == 0: print "Nothing to apply." and return
7. If not auto_yes: input("Apply N heals to <workflow>? [Y/n]: ") — skip on 'n'
8. Patch each matched step's "element" field
9. Write updated JSON back to workflow_path (indent=2, ensure_ascii=False)
10. Print f"{n} heal(s) applied to {workflow_path}. Commit to make permanent."

Do NOT touch healer files, POM files, or Glue files.
All existing exam tests must still pass: pytest exam/ -x -q

Verify:
  # Generate heal_suggestions.json by running a workflow with --heal 1 against a broken locator
  python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json
  # Shows diff, prompts for Y/n
  python stepper/main.py --apply-heals stepper/sites/saucedemo/workflows/checkout.json --yes
  # Patches silently, prints "N heal(s) applied"
  pytest exam/ -x -q

After done, update plans/self-improving-healer/PROGRESS.md phase 3 and overall Status to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `--apply-heals` reads suggestions, shows diff, patches workflow JSON; exam tests pass.
**Files touched:** `stepper/main.py`

---

## Conversation 4: StepRunner Refactor (Phase 4)

**Prompt to paste:**
```
Implement Self-Improving Healer Conversation 4 (Phase 4) from plans/self-improving-healer/IMPLEMENTATION_PLAN.md.
Conversations 1–3 are DONE: VisualBridge, HealCache, and --apply-heals are all wired.

Scope — Phase 4: Refactor stepper/engine/runner/step_runner.py (no behaviour change)

The goal is to shrink `run()` from ~200 lines to ~50 lines by extracting private helpers.
No logic must change — only structure. All existing tests must pass before and after.

Extract the following private methods on StepRunner:

1. `async _run_step(self, idx, step, steps, ctx) -> StepResult`
   - Contains: resolve_count_vars, CAPTCHA check, inter-step delay, retry loop, heal loop, auto-screenshot
   - Returns the final StepResult for that step
   - `run()` calls this and then handles reporter + observer + hard-stop logic

2. `async _run_retry_loop(self, idx, step, ctx) -> StepResult`
   - Contains: the `for attempt in range(max_attempts)` block (action create, execute, sleep on retry)
   - Returns the last StepResult from the retry attempts

3. `async _run_heal_loop(self, idx, step, steps, result, ctx) -> tuple[StepResult, list[dict]]`
   - Contains: the entire `while heal_attempt < self._max_heal_attempts` block
     (cache check, visual bridge check, DOMSnapshotCascade, replacement_runner, heal_assert, HealAnnotator, notify_log)
   - Returns (updated_result, new_heal_suggestions) where new_heal_suggestions is a list (empty if no heal occurred)
   - Caller (`_run_step`) extends the outer `heal_suggestions` list with the returned list

Call hierarchy after refactor:
  run()
    └─ _run_step()
         ├─ _run_retry_loop()
         └─ _run_heal_loop()  (only if failed/skipped and healer present)

Rules:
- Do NOT change any logic, conditions, log messages, or return values
- Do NOT rename any existing public methods or constructor parameters
- Do NOT touch any file outside stepper/engine/runner/step_runner.py
- _run_heal_assert() at module level stays where it is

Verify:
  python -c "from engine.runner.step_runner import StepRunner; print('ok')"
  pytest exam/ -x -q

After done, update plans/self-improving-healer/PROGRESS.md phase 4 to DONE and overall Status to DONE.

If any test fails, rollback with git checkout stepper/engine/runner/step_runner.py and report.
```

**Expected output:** `run()` is ~50 lines; all logic unchanged; exam tests pass.
**Files touched:** `stepper/engine/runner/step_runner.py`
