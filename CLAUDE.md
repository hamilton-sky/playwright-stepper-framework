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
│   │   ├── runner/                   # StepRunner, when_eval
│   │   ├── planner/                  # Claude AI planner / JSON planner
│   │   ├── reporter/                 # Reporters + test report manager
│   │   └── pages/                    # PageModule ABC + POM registry
│   └── sites/                        # Glue layer — wires POMs into Stepper actions
│       ├── openlibrary/pages/
│       ├── saucedemo/pages/
│       ├── phptravels/pages/
│       └── */workflows/*.json        # Declarative workflow definitions
│
├── examples/
│   └── plain_pom/                    # Reference: POMs driven with no engine, no resolver
│       ├── conftest.py
│       ├── flows.py
│       └── tests/test_openlibrary_flows.py
│
├── docs/playwright-pitfalls.md       # Failure modes the POMs guard against
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
| Playwright failure modes the POMs guard against | [docs/playwright-pitfalls.md](docs/playwright-pitfalls.md) |
| Full architecture diagrams | [ARCHITECTURE.md](ARCHITECTURE.md) |

---

## Run Commands

```bash
# Unit suite — no browser, no network, no credentials. Start here.
PYTHONPATH=stepper pytest stepper/tests/unit/

# Stepper integration tests (real browser)
PYTHONPATH=stepper pytest stepper/tests/ --ignore=stepper/tests/unit

# Plain-POM example suite (real browser + OpenLibrary credentials)
cd examples/plain_pom && pytest tests/

# Run a workflow
python stepper/main.py --workflow stepper/sites/openlibrary/workflows/<file>.json

# Show browser window (headless is the default)
python stepper/main.py --workflow <file>.json --show
```

---

## Adding a New Site (quick reference)

1. `poms/<site>/pages/base_page.py` — inherit `SharedBasePage`
2. Add POM files — every interactive locator a `Locator` object (see [pom-layer rules](.claude/rules/pom-layer.md))
3. `stepper/sites/<site>/pages/` — one glue file per logical group
4. Build POMs via `self._build_pom(..., page=page, resolver=resolver, behaviour=behaviour)` (see [glue-layer rules](.claude/rules/glue-layer.md))
5. Register actions in each PageModule's `register(registry)` classmethod
6. Wire that PageModule into `stepper/sites/<site>/register.py`
