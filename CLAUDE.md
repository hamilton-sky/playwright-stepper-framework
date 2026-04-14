# Stepper Framework — Claude Code Guide

## Directory Structure

```
playwright-stepper-framework/
│
├── poms/                             # Pure Page Object Model layer
│   ├── shared/                       # Shared across ALL sites
│   │   ├── base_page.py              # SharedBasePage — resolver helpers
│   │   ├── driver.py                 # PlaywrightDriver (IBrowserDriver impl)
│   │   ├── interfaces.py             # IBrowserDriver, IElementHandle, Delays
│   │   └── performance.py            # Performance metrics
│   ├── openLibrary/                  # OpenLibrary POMs
│   ├── saucedemo/                    # SauceDemo POMs
│   └── phpTravels/                   # phpTravels POMs
│
├── stepper/                          # The Automation Engine
│   ├── main.py                       # Entry point
│   ├── engine/                       # Core framework modules
│   │   ├── actions/                  # ActionRegistry + strategies
│   │   ├── resolvers/                # Element resolution cascade
│   │   ├── runner/                   # StepRunner, when_eval, API
│   │   ├── planner/                  # Claude AI planner / JSON planner
│   │   ├── reporter/                 # Reporters + test report manager
│   │   └── pages/                    # PageModule ABC + POM registry
│   └── sites/                        # Glue layer — wires POMs into Stepper actions
│       ├── openlibrary/pages/
│       ├── saucedemo/pages/
│       ├── phptravels/pages/
│       └── */workflows/*.json        # Declarative workflow definitions
│
├── exam/                             # Exam test layer (OpenLibrary)
│   ├── conftest.py
│   ├── flows.py
│   └── tests/test_openlibrary_exam.py
│
├── ARCHITECTURE.md                   # Full architecture diagrams
└── CLAUDE.md                         # This file
```

---

## Instruction Routing

Read the relevant rule file **before** making changes in that area:

| Area | Rule file |
|---|---|
| POM layer (locators, selectors, page interactions) | [.claude/rules/pom-layer.md](.claude/rules/pom-layer.md) |
| Glue layer (action wiring, resolver injection) | [.claude/rules/glue-layer.md](.claude/rules/glue-layer.md) |
| Element resolver cascade | [.claude/rules/resolver-cascade.md](.claude/rules/resolver-cascade.md) |
| Site-specific action reference tables | [.claude/rules/site-actions.md](.claude/rules/site-actions.md) |
| Three-layer contract + dependency direction | [.claude/rules/three-layer-contract.md](.claude/rules/three-layer-contract.md) |
| Design patterns used throughout the framework | [.claude/rules/design-patterns.md](.claude/rules/design-patterns.md) |
| Full architecture diagrams | [ARCHITECTURE.md](ARCHITECTURE.md) |

---

## Run Commands

```bash
# Run all exam tests
pytest exam/

# Run a specific test
pytest exam/tests/test_openlibrary_exam.py -k <test_name>

# Run a workflow
python stepper/main.py --workflow stepper/sites/openlibrary/workflows/<file>.json

# Run headless
python stepper/main.py --workflow <file>.json --headless
```

---

## Adding a New Site (quick reference)

1. `poms/<site>/pages/base_page.py` — inherit `SharedBasePage`
2. Add POM files — all interactive locators as cfg lists (see [pom-layer rules](.claude/rules/pom-layer.md))
3. `stepper/sites/<site>/pages/` — one glue file per logical group
4. Pass `page=page, resolver=resolver` on every POM construction (see [glue-layer rules](.claude/rules/glue-layer.md))
5. Register actions in each glue file's `register()` classmethod
