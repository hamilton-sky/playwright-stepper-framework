# Refactor main.py — Conversation Guide

Split into 3 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: Extract Helper Functions (Phases 1–4)

**Prompt to paste:**
```
Implement Refactor main.py Conversation 1 (Phases 1–4) from plans/refactor-main/IMPLEMENTATION_PLAN.md.

Context: stepper/main.py has a 180-line god function run() that does 6 unrelated jobs.
Conversations 2 and 3 depend on this conversation being DONE first.

Scope — all changes stay in stepper/main.py only:

Phase 1 — _load_settings_safe():
  Create a module-level _RunSettings NamedTuple and a private _load_settings_safe() function
  that wraps the try/except settings loading and returns a _RunSettings instance.
  Replace the identical try/except blocks in both run() and _run_data_rows() with calls
  to this function. Access fields by name (s.use_visual_ai, s.browser) — not positional unpacking.
  See IMPLEMENTATION_PLAN.md Phase 1 for the exact signature.

Phase 2 — _build_resolver(use_visual_ai):
  Create a module-level private function that constructs and returns an ElementResolver.
  In run(): call _build_resolver(use_visual_ai) where resolver is None.
  In _run_data_rows(): replace the inline resolver construction with _build_resolver().
  See IMPLEMENTATION_PLAN.md Phase 2.

Phase 3 — _build_reporters(run_label, cfg_browser, headless, stepper_root):
  Create a module-level private function that constructs all four reporters and returns
  (CompositeReporter, TestReportReporter). Replace the inline reporter block in run().
  See IMPLEMENTATION_PLAN.md Phase 3.

Phase 4 — _launch_browser(pw, cfg_browser, headless, slow_mo):
  Create a module-level async private function for browser launch.
  Replace the inline launcher dict + launch() call in run() (the _owns_browser branch)
  and in _run_data_rows() with calls to this function.
  Preserve the anti-detection arg: ["--disable-blink-features=AutomationControlled"].
  See IMPLEMENTATION_PLAN.md Phase 4.

Rules:
- Only edit stepper/main.py — do NOT touch any other file.
- run() and _run_data_rows() must produce identical observable behaviour after refactor.
- All four helpers are private (underscore prefix), module-level functions.

Verify: python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json --show

After done, update plans/refactor-main/PROGRESS.md phases 1–4 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with: git checkout stepper/main.py
```

**Expected output:** `main.py` has 4 new helper functions; `run()` is ~100 lines shorter; behaviour unchanged.
**Files touched:** `stepper/main.py`, `plans/refactor-main/PROGRESS.md`

---

## Conversation 2: Site Auto-Discovery (Phases 5–6)

**Prompt to paste:**
```
Implement Refactor main.py Conversation 2 (Phases 5–6) from plans/refactor-main/IMPLEMENTATION_PLAN.md.

Context: Conversations 1 is DONE — main.py now has _load_settings_safe, _build_resolver,
_build_reporters, and _launch_browser helpers. Now we make site registration auto-discoverable.

Scope:

Phase 5 — Per-site register.py files:
  Create stepper/sites/openlibrary/register.py with a register(registry, screenshots_dir=None)
  function that imports and registers all OL glue actions (OLSearchPage, OLDetailPage,
  OLReadingListPage, OLLoginPage) exactly as they are currently registered in main.py.
  Check stepper/sites/saucedemo/pages/ to see what SauceDemo actions exist and create
  stepper/sites/saucedemo/register.py accordingly.
  Check stepper/sites/phptravels/pages/ to see what phpTravels actions exist and create
  stepper/sites/phptravels/register.py accordingly.
  See IMPLEMENTATION_PLAN.md Phase 5 for the pattern.

Phase 6 — _register_all_sites() in main.py:
  Create a module-level private function _register_all_sites(registry, screenshots_dir=None)
  that uses importlib to glob stepper/sites/*/register.py and calls register() on each.
  Failures on a single site must log a warning and continue — never crash.
  In run(), replace the hardcoded OL import block (the 8 lines importing and calling
  OLSearchPage.register etc.) with a call to _register_all_sites(action_registry, screenshots_dir=screenshots_dir).
  See IMPLEMENTATION_PLAN.md Phase 6.

Rules:
- Do NOT edit any existing glue file (stepper/sites/*/pages/*.py).
- Do NOT edit any POM file.
- The register.py files must NOT duplicate logic — they only import and forward to the
  existing .register() classmethods on each glue action class.

Verify: python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json

After done, update plans/refactor-main/PROGRESS.md phases 5–6 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with: git checkout stepper/main.py stepper/sites/
```

**Expected output:** 3 new `register.py` files; `main.py` no longer hardcodes site imports; all sites still register.
**Files touched:** `stepper/sites/openlibrary/register.py` (NEW), `stepper/sites/saucedemo/register.py` (NEW), `stepper/sites/phptravels/register.py` (NEW), `stepper/main.py`, `plans/refactor-main/PROGRESS.md`

---

## Conversation 3: Fix Temporal Coupling (Phase 7)

**Prompt to paste:**
```
Implement Refactor main.py Conversation 3 (Phase 7) from plans/refactor-main/IMPLEMENTATION_PLAN.md.

Context: Conversations 1–2 are DONE. main.py has helper functions and auto-discovery.
Now fix the temporal coupling on RunWorkflowAction.

Scope:

Phase 7 — RunWorkflowAction temporal coupling:
  In run(), find the block that registers RunWorkflowAction. It currently has a comment
  "TEMPORAL COUPLING: RunWorkflowAction MUST be registered after StepRunner is constructed."
  Fix this by simply moving the RunWorkflowAction import and registration to AFTER
  the StepRunner construction block (after runner.add_observer(LoggingObserver())).
  Remove the temporal-coupling comment entirely. No lambda, no cell pattern needed.
  See IMPLEMENTATION_PLAN.md Phase 7 for the exact pattern.

Rules:
- Only edit stepper/main.py.
- RunWorkflowAction import and base_dir logic stays the same.
- Move the RunWorkflowAction block to after StepRunner is constructed — do NOT use
  _runner_ref or any lambda indirection.

Verify: python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json

After done, update plans/refactor-main/PROGRESS.md phase 7 to DONE and overall Status to COMPLETE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with: git checkout stepper/main.py
```

**Expected output:** No temporal-coupling comment; `RunWorkflowAction` registered before `StepRunner` construction; behaviour identical.
**Files touched:** `stepper/main.py`, `plans/refactor-main/PROGRESS.md`
