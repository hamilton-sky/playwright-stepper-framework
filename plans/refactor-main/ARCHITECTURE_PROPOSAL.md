# Refactor main.py — Architecture Proposal

## Problem Statement
`stepper/main.py`'s `run()` function is a 180-line god function that owns settings
loading, resolver construction, reporter wiring, browser launch, site registration,
and step execution. Two of those responsibilities (settings loading) are copy-pasted
into `_run_data_rows()`. Site registration is hardcoded, forcing every new site to
edit `main.py` (OCP violation). A temporal coupling comment warns that code blocks
must remain in a specific order or a NameError occurs.

## Proposed Solution
Extract each responsibility into a focused private helper. Replace hardcoded site
imports with a glob-based auto-discovery pattern. Fix temporal coupling with a
one-element list cell (poor man's mutable ref). All changes stay in `main.py` and
new `sites/*/register.py` files — no engine or POM changes.

## Three-Layer Breakdown

```
Flow layer   (stepper/sites/*/workflows/*.json)
     │  unchanged
     ▼
Glue layer   (stepper/sites/*/pages/*.py)
     │  unchanged — register() classmethods already exist
     ▼
     sites/*/register.py          ← NEW: thin wrapper, calls existing register()
     │
     ▼
stepper/main.py
     ├── _load_settings_safe()    ← extracted from run() + _run_data_rows()
     ├── _build_resolver()        ← extracted from run() + _run_data_rows()
     ├── _build_reporters()       ← extracted from run()
     ├── _launch_browser()        ← extracted from run() + _run_data_rows()
     ├── _register_all_sites()    ← NEW: replaces hardcoded imports
     └── run()                    ← now ~80 lines; orchestration only
```

## Key Design Decisions

### Decision 1: Private helpers in main.py, not a new module
- **Options**: A) helpers in `main.py`, B) new `engine/bootstrap.py`, C) new `stepper/bootstrap.py`
- **Chosen**: A
- **Rationale**: This is a cleanup refactor, not a new capability. Moving to a new module
  would require updating imports elsewhere and risks circular deps. `main.py` is the
  composition root — helpers belong here until there's a real reason to move them.

### Decision 2: glob-based discovery over explicit registry
- **Options**: A) glob `sites/*/register.py`, B) explicit list in config/settings,
  C) `__init__.py` side-effect imports
- **Chosen**: A
- **Rationale**: Convention over configuration. Developer drops `register.py` → it works.
  No central list to forget to update. Easy to test in isolation. `__init__.py` side-effects
  are confusing and order-dependent.

### Decision 3: Fix temporal coupling by reordering, not by indirection
- **Options**: A) move `RunWorkflowAction` registration after `StepRunner` construction,
  B) `_runner_ref = []` cell with a lambda, C) restructure StepRunner to accept run_callable post-construction
- **Chosen**: A
- **Rationale**: The coupling exists only because the original code registered the action
  before the runner was constructed. Moving two blocks into correct order eliminates the
  problem at its source. Option B trades one ordering constraint for another (`IndexError`
  on `_runner_ref[0]` is the same fragility in a less obvious form). Option C is out of scope.

## New Files
- `stepper/sites/openlibrary/register.py`
- `stepper/sites/saucedemo/register.py`
- `stepper/sites/phptravels/register.py`

## New Functions in main.py
| Function | Returns | Replaces |
|---|---|---|
| `_load_settings_safe()` | `(bool, int, str, str\|None)` | duplicate try/except ×2 |
| `_build_resolver(use_visual_ai)` | `ElementResolver` | inline construction ×2 |
| `_build_reporters(label, browser, headless, root)` | `(CompositeReporter, TestReportReporter)` | inline block in run() |
| `_launch_browser(pw, browser, headless, slow_mo)` | browser instance | inline launcher dict ×2 |
| `_register_all_sites(registry, screenshots_dir)` | None | 8-line hardcoded import block |

## Risks
- **Glob finds partial/broken register.py**: Mitigated — per-site try/except logs warning and continues.
- **SauceDemo/phpTravels register.py imports fail**: Acceptable — those sites may have incomplete actions; warning is correct behaviour.
- **RunWorkflowAction ordering**: Fixed by correct ordering (registered after StepRunner construction). No cell/lambda pattern used — avoids the IndexError fragility of that approach.
