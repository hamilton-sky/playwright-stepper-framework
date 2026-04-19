# Refactor main.py — Implementation Plan

## Overview
Split `stepper/main.py`'s 180-line god function `run()` into focused private helpers.
Eliminate the settings-loading duplication between `run()` and `_run_data_rows()`.
Make site registration auto-discoverable so new sites never require editing `main.py`.
Fix the temporal coupling on `RunWorkflowAction`.
All changes are in `stepper/main.py` and `stepper/sites/*/register.py` — no POM or
engine changes required.

## Layer Architecture

```
Flow (JSON)  →  Glue (stepper/sites/…)  →  POM (poms/…)
                         ↑
              stepper/sites/*/register.py   ← NEW (per-site)
                         ↑
              stepper/main.py helpers       ← REFACTORED
```

---

## Phases

### Phase 1: Extract `_load_settings_safe()` (small)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — extract duplicated try/except settings block into one helper

**Details:**
Create a private NamedTuple and function at module level:
```python
from typing import NamedTuple

class _RunSettings(NamedTuple):
    use_visual_ai: bool
    slow_mo: int
    browser: str
    storage_state_path: str | None

def _load_settings_safe() -> _RunSettings:
    try:
        settings = load_settings()
        validate_ai_config(settings)
        return _RunSettings(settings.use_visual_ai, settings.slow_mo_ms, settings.browser, settings.storage_state_path)
    except Exception:
        return _RunSettings(False, 300, "chromium", None)
```
Replace both try/except blocks in `run()` and `_run_data_rows()` with a call to this function.
Callers access fields by name (`s.use_visual_ai`, `s.browser`) — not positional unpacking.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json`

---

### Phase 2: Extract `_build_resolver()` (small)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — extract resolver construction from `run()`

**Details:**
```python
def _build_resolver(use_visual_ai: bool) -> ElementResolver:
    ai_client = None
    if use_visual_ai:
        import anthropic
        ai_client = anthropic.Anthropic()
    factory = DefaultResolverFactory()
    return ElementResolver(
        strategies=factory.build_cascade(),
        ai_client=ai_client,
        use_visual_ai=use_visual_ai,
    )
```
`run()` calls `_build_resolver(use_visual_ai)` when `resolver is None`.
`_run_data_rows()` calls `_build_resolver(use_visual_ai)` instead of inline construction.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json`

---

### Phase 3: Extract `_build_reporters()` (small)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — extract reporter wiring from `run()`

**Details:**
```python
def _build_reporters(run_label: str, cfg_browser: str, headless: bool, stepper_root: Path):
    test_reporter = TestReportReporter(
        reports_base=str(stepper_root / "reports"),
        test_name=run_label,
        browser=cfg_browser,
        headless=not headless,
    )
    reporters = [
        ConsoleReporter(),
        JsonReporter(str(stepper_root / "report.json")),
        test_reporter,
        AllureReporter(str(stepper_root / "reports" / "allure-results")),
    ]
    return CompositeReporter(reporters), test_reporter
```
`run()` calls this instead of inline construction.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json`

---

### Phase 4: Extract `_launch_browser()` (small)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — extract browser launch from `run()` and `_run_data_rows()`

**Details:**
```python
async def _launch_browser(pw, cfg_browser: str, headless: bool, slow_mo: int):
    launchers = {
        "chromium": pw.chromium,
        "firefox": pw.firefox,
        "webkit": pw.webkit,
    }
    return await launchers.get(cfg_browser, pw.chromium).launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled"],
    )
```
Both `run()` (when `_owns_browser`) and `_run_data_rows()` call this.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json --show`

---

### Phase 5: Create per-site `register.py` files (medium)
**Layer:** Glue (stepper/sites/)
**Files:**
- `stepper/sites/openlibrary/register.py` — NEW
- `stepper/sites/saucedemo/register.py` — NEW
- `stepper/sites/phptravels/register.py` — NEW

**Details:**
Each file exposes one function `register(registry, **kwargs)`:

```python
# stepper/sites/openlibrary/register.py
def register(registry, screenshots_dir=None):
    from sites.openlibrary.pages.search_page import OLSearchPage
    from sites.openlibrary.pages.detail_page import OLDetailPage
    from sites.openlibrary.pages.reading_list_action import OLReadingListPage
    from sites.openlibrary.pages.login_action import OLLoginPage

    OLSearchPage.register(registry)
    OLDetailPage.register(registry, screenshots_dir=screenshots_dir)
    OLReadingListPage.register(registry)
    OLLoginPage.register(registry)
```

SauceDemo and phpTravels follow same pattern with their own imports.

**Verify:** Each file can be imported without error:
`python -c "from sites.openlibrary.register import register; print('ok')"` (run from stepper/)

---

### Phase 6: Auto-discover sites in `main.py` (medium)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — replace hardcoded site imports with auto-discovery

**Details:**
```python
def _register_all_sites(registry, screenshots_dir=None):
    sites_root = Path(__file__).parent / "sites"
    for register_py in sites_root.glob("*/register.py"):
        site_name = register_py.parent.name
        try:
            import importlib
            mod = importlib.import_module(f"sites.{site_name}.register")
            mod.register(registry, screenshots_dir=screenshots_dir)
            logger.debug(f"Registered site: {site_name}")
        except Exception as e:
            logger.warning(f"Site '{site_name}' register failed: {e}")
```
Replace the hardcoded OL import block in `run()` with `_register_all_sites(action_registry, screenshots_dir=screenshots_dir)`.

**Verify:** `python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json`

---

### Phase 7: Fix RunWorkflowAction temporal coupling (small)
**Layer:** main.py only
**Files:**
- `stepper/main.py` — reorder two lines so `RunWorkflowAction` is registered after `StepRunner`

**Details:**
Move the `RunWorkflowAction` registration to **after** `StepRunner` is constructed.
The current code has a warning comment because the registration appears before the runner exists.
The fix is simply correct ordering — no new indirection needed:

```python
runner = StepRunner(
    page=page,
    action_factory=action_registry,
    resolver=resolver,
    reporter=reporter,
    screenshots_dir=screenshots_dir,
)
runner.add_observer(LoggingObserver())

# Registered here — after runner exists, so runner.run is a valid callable.
from engine.actions.strategies import RunWorkflowAction
base_dir = Path(workflow_path).parent if workflow_path else Path.cwd()
action_registry.register(RunWorkflowAction(run_steps_callable=runner.run, base_dir=base_dir))
```

Remove the temporal-coupling comment entirely.

**Why not the `_runner_ref = []` cell approach:** the cell pattern trades one ordering constraint
for another — `_runner_ref[0]` raises `IndexError` if called before `append(runner)`, which is
the same fragility in a less obvious form. Correct ordering is simpler and has no hidden failure mode.

**Verify:** Run a workflow that uses `run_workflow` sub-steps, or smoke-test any workflow.

---

## Prerequisites
- No outstanding changes to `run()` or `_run_data_rows()` on the branch
- All existing exam tests pass before starting: `pytest exam/`

## Key Decisions
- **No new files in engine/**: All helpers stay in `main.py` as private functions. Avoids over-engineering for a cleanup refactor.
- **sites/*/register.py not sites/*/pages/__init__.py**: Explicit `register.py` is easier to discover and grep than side-effecting `__init__.py` imports.
- **Reorder over `_runner_ref` cell**: Correct ordering eliminates the coupling at source. The cell pattern trades one ordering constraint for another (`IndexError` on `_runner_ref[0]`).
