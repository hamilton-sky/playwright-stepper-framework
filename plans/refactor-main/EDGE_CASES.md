# Refactor main.py — Edge Cases

## Category 1: Settings Load Failures

### EC-1.1: Config file missing entirely
- **Trigger**: `.env` or `poms/openLibrary/config.py` raises on import
- **Current behavior**: try/except silently applies fallback defaults (headless, 300ms, chromium)
- **Expected behavior**: same — `_load_settings_safe()` must preserve this fallback
- **Handled in**: Phase 1 — the helper wraps the same except clause

### EC-1.2: Partial config (field missing)
- **Trigger**: Config exists but `use_visual_ai` or `slow_mo_ms` attribute absent
- **Current behavior**: exception caught, full fallback applied
- **Expected behavior**: same
- **Handled in**: Phase 1 — single except catches AttributeError too

---

## Category 2: Site Auto-Discovery

### EC-2.1: register.py import error in one site
- **Trigger**: A site's `register.py` has a broken import (e.g. missing POM file)
- **Current behavior**: N/A — hardcoded, so broken import crashes main.py
- **Expected behavior**: log warning, skip that site, other sites still register
- **Handled in**: Phase 6 — try/except per site in `_register_all_sites()`

### EC-2.2: Empty sites/ folder or no register.py files
- **Trigger**: `stepper/sites/` contains no `register.py` files (e.g. fresh repo)
- **Current behavior**: N/A
- **Expected behavior**: glob returns empty list, no actions registered, workflow
  fails on first action with "unknown action" error (not a crash in main.py)
- **Handled in**: Phase 6 — `glob()` returning empty is a no-op loop

### EC-2.3: register.py exists but register() function missing
- **Trigger**: Developer creates `register.py` without the required function
- **Expected behavior**: `AttributeError` caught by per-site try/except, warning logged
- **Handled in**: Phase 6 — same catch block as EC-2.1

---

## Category 3: Temporal Coupling Fix

### EC-3.1: _runner_ref accessed before StepRunner constructed
- **Trigger**: A sub-workflow fires before `_runner_ref.append(runner)` executes
- **Expected behavior**: `IndexError: list index out of range` — clear error, not silent
- **Handled in**: Phase 7 — the lambda fires only when `run_workflow` action executes,
  which is after `StepRunner` is fully constructed and `_runner_ref` is populated

### EC-3.2: RunWorkflowAction not needed (no sub-workflows)
- **Trigger**: Workflow JSON has no `run_workflow` steps
- **Expected behavior**: lambda is never called; `_runner_ref` is populated but unused
- **Handled in**: Phase 7 — no-op; no regression

---

## Category 4: Data-Driven Mode

### EC-4.1: _run_data_rows shares resolver but not browser between rows
- **Trigger**: Resolver is stateless and built once; browser is shared across rows
- **Current behavior**: works correctly; resolver is reused
- **Expected behavior**: same after `_build_resolver()` extraction
- **Handled in**: Phase 2 — `_run_data_rows()` calls `_build_resolver()` once,
  same as current inline construction

---

## Known Limitations
- `poms/openLibrary/config.py` acting as global settings source is NOT fixed in this plan.
  That is a separate, higher-risk refactor requiring engine/ changes.
- SauceDemo site registration may not currently work (actions may be missing).
  `saucedemo/register.py` will wrap whatever actions actually exist — it won't fix missing actions.
