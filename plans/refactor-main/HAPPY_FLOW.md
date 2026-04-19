# Refactor main.py — Happy Flow

## Overview
After the refactor, a developer adds a new site (e.g. `stepper/sites/booking/`) by
dropping a `register.py` in that folder. `main.py` auto-discovers it on the next run.
No other file changes needed. The existing OpenLibrary search-and-add workflow still
runs end-to-end without any observable difference.

---

## Step-by-Step Happy Flow (post-refactor run)

### Step 1: CLI parses args
- `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json`
- `main()` calls `_load_env()`, parses args, dispatches to `asyncio.run(run(…))`

### Step 2: Settings load
- `run()` calls `_load_settings_safe()` → returns `(use_visual_ai, slow_mo, cfg_browser, storage_state_path)`
- No duplication with `_run_data_rows()`

### Step 3: Resolver built
- `run()` calls `_build_resolver(use_visual_ai)` → returns configured `ElementResolver`
- AI client only created if `use_visual_ai=True`

### Step 4: Reporters built
- `run()` calls `_build_reporters(run_label, cfg_browser, headless, _stepper_root)`
- Returns `(CompositeReporter, TestReportReporter)` — four reporters wired inside

### Step 5: Browser launched
- `run()` calls `await _launch_browser(pw, cfg_browser, headless, slow_mo)`
- Returns browser instance; anti-detection arg applied

### Step 6: Sites auto-registered
- `_register_all_sites(action_registry, screenshots_dir=screenshots_dir)` globs `sites/*/register.py`
- Discovers openlibrary, saucedemo, phptravels → calls each `register()` function
- New sites just work by having a `register.py`

### Step 7: RunWorkflowAction registered (no ordering constraint)
- `StepRunner` constructed first
- `RunWorkflowAction` registered immediately after, passing `runner.run` directly — no indirection needed

### Step 8: Workflow executes
- `runner.run(steps)` executes all workflow steps
- Reporters capture results; suite finishes; reports written

---

## End State
- Workflow ran successfully; reports in `stepper/reports/`
- No behaviour change from pre-refactor

## Success Indicators
- [ ] `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json` exits 0
- [ ] `stepper/reports/` contains a new run folder with logs and screenshots
- [ ] No site imports visible in `run()` body — only `_register_all_sites()` call
- [ ] `main.py` has no duplicated try/except settings blocks
