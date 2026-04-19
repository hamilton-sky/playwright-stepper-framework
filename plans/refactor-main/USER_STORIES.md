# Refactor main.py — User Stories

## Context
`stepper/main.py` is a single 356-line file containing a god function `run()` that
does six unrelated jobs: settings loading, resolver construction, reporter wiring,
browser launch, site registration, and step execution. Settings loading is copy-pasted
between `run()` and `_run_data_rows()`. Site registration is hardcoded, so every new
site requires editing `main.py` (OCP violation). This refactor splits the function into
focused helpers and makes site registration auto-discoverable.

---

## Stories

### Story 1.1: Extract Settings Loading
**As a** framework developer, **I want** settings loading in one place,
**so that** I don't maintain two copies of the same try/except block.

**Acceptance Criteria:**
- [ ] Single `_load_settings_safe()` function returns a settings namedtuple
- [ ] Both `run()` and `_run_data_rows()` call it
- [ ] Fallback defaults (headless=True, slow_mo=300, chromium) still apply on failure

**Edge Cases:**
- Config file missing entirely → fallback defaults, no crash
- Partial config (missing `use_visual_ai`) → fallback defaults

---

### Story 1.2: Extract Resolver Construction
**As a** framework developer, **I want** resolver building in a focused helper,
**so that** I can test or swap the resolver independently of the full run loop.

**Acceptance Criteria:**
- [ ] `_build_resolver(settings)` returns a configured `ElementResolver`
- [ ] AI client only created when `settings.use_visual_ai` is True
- [ ] `run()` calls `_build_resolver()` when no external resolver is injected

**Edge Cases:**
- `use_visual_ai=True` but no ANTHROPIC_API_KEY → anthropic raises, not main.py

---

### Story 1.3: Extract Reporter Construction
**As a** framework developer, **I want** reporter wiring in one helper,
**so that** adding a new reporter type requires touching only that helper.

**Acceptance Criteria:**
- [ ] `_build_reporters(run_label, settings, stepper_root)` returns `(CompositeReporter, TestReportReporter)`
- [ ] All four reporter types still wired (Console, JSON, TestReport, Allure)
- [ ] Absolute path anchoring to `_stepper_root` preserved

**Edge Cases:**
- `_stepper_root` doesn't exist yet → reporters create dirs lazily (existing behavior)

---

### Story 1.4: Extract Browser Launch
**As a** framework developer, **I want** browser launch logic in one helper,
**so that** `run()` and `_run_data_rows()` don't duplicate launcher dict logic.

**Acceptance Criteria:**
- [ ] `_launch_browser(pw, settings, headless)` returns a browser instance
- [ ] Supports chromium / firefox / webkit
- [ ] Anti-detection args (`--disable-blink-features=AutomationControlled`) preserved

**Edge Cases:**
- Unknown browser name in settings → falls back to chromium

---

### Story 1.5: Auto-Discover Site Registrations
**As a** framework developer, **I want** sites to register themselves,
**so that** adding a new site never requires editing `main.py`.

**Acceptance Criteria:**
- [ ] Each `stepper/sites/<site>/` has a `register.py` with `register(registry)` function
- [ ] `main.py` discovers and calls all `register.py` files dynamically
- [ ] Existing OpenLibrary, SauceDemo, phpTravels actions still register correctly

**Edge Cases:**
- `register.py` import fails → log warning, skip that site, don't crash
- Empty `register.py` → no-op, no crash

---

### Story 1.6: Fix Temporal Coupling for RunWorkflowAction
**As a** framework developer, **I want** RunWorkflowAction registered without a
mandatory ordering comment,
**so that** the setup code is safe to reorder without risk of NameError.

**Acceptance Criteria:**
- [ ] Temporal coupling comment removed
- [ ] `RunWorkflowAction` receives the callable at the point it's needed, not via post-construction registration
- [ ] Sub-workflow execution still works

**Edge Cases:**
- Runner not yet constructed when registry is built → lazy callable resolves correctly
