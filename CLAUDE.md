# Stepper Framework — Claude Code Guide

## Directory Structure

```
playwright-stepper-framework/
│
├── poms/                             # Pure Page Object Model layer
│   ├── shared/                       # Shared across ALL sites
│   │   ├── base_page.py              # SharedBasePage — resolver helpers, all sites inherit
│   │   ├── driver.py                 # PlaywrightDriver (IBrowserDriver impl)
│   │   ├── interfaces.py             # IBrowserDriver, IElementHandle, Delays
│   │   └── performance.py            # Performance metrics
│   │
│   ├── openLibrary/                  # OpenLibrary POMs
│   │   ├── config.py                 # Settings loader (YAML + env vars)
│   │   ├── pages/
│   │   │   ├── base_page.py          # OL BasePage(SharedBasePage) — adds delays
│   │   │   ├── login_page.py
│   │   │   ├── book_search_page.py
│   │   │   ├── book_detail_page.py
│   │   │   └── reading_list_page.py
│   │   ├── utils/
│   │   │   ├── book_filter.py
│   │   │   ├── screenshot.py
│   │   │   └── shelf.py
│   │   └── data/testdata.json
│   │
│   ├── saucedemo/                    # SauceDemo POMs
│   │   ├── config.py
│   │   ├── pages/
│   │   │   ├── base_page.py          # SD BasePage(SharedBasePage)
│   │   │   ├── login_page.py
│   │   │   ├── inventory_page.py
│   │   │   ├── product_page.py
│   │   │   ├── cart_page.py
│   │   │   ├── checkout_info_page.py
│   │   │   ├── checkout_overview_page.py
│   │   │   └── checkout_complete_page.py
│   │   └── data/testdata.json
│   │
│   └── phpTravels/                   # phpTravels POMs
│       └── pages/
│           ├── base_page.py          # PT BasePage(SharedBasePage)
│           ├── login_page.py
│           ├── home_page.py
│           ├── hotel_results_page.py
│           └── hotel_detail_page.py
│
├── stepper/                          # The Automation Engine
│   ├── main.py                       # Entry point
│   ├── stepper/                      # Core framework modules
│   │   ├── interfaces.py             # Strategy/Observer abstractions + StepConfig
│   │   ├── actions/
│   │   │   ├── factory.py            # ActionRegistry
│   │   │   └── strategies.py         # Navigate, Click, Fill, ForEach, Parallel, etc.
│   │   ├── resolvers/
│   │   │   ├── element_resolver.py   # Cascade orchestrator (det → semantic → AI)
│   │   │   ├── strategies.py         # 7 deterministic resolver strategies
│   │   │   └── ai_pick_resolver.py   # AI disambiguation (Groq → Gemini → Claude)
│   │   ├── runner/
│   │   │   ├── step_runner.py        # Execution loop (retry + observers)
│   │   │   ├── when_eval.py          # Conditional step evaluation
│   │   │   └── api.py                # Programmatic API
│   │   ├── planner/
│   │   │   └── planner.py            # Claude AI planner / JSON file planner
│   │   ├── reporter/
│   │   │   ├── reporters.py
│   │   │   ├── test_report_manager.py
│   │   │   └── test_report_reporter.py
│   │   └── pages/
│   │       ├── base_page_module.py   # PageModule ABC
│   │       └── page_objects.py       # POM registry
│   │
│   ├── sites/                        # Glue layer — wires POMs into Stepper actions
│   │   ├── openlibrary/pages/
│   │   │   ├── login_action.py       # ol_ensure_login
│   │   │   ├── search_page.py        # ol_collect_books / collect_items
│   │   │   ├── detail_page.py        # ol_add_to_shelf
│   │   │   └── reading_list_action.py # ol_clear_reading_list, ol_store_count,
│   │   │                              #   ol_assert_count, ol_ensure_count
│   │   ├── saucedemo/pages/
│   │   │   ├── login_action.py       # sd_login
│   │   │   ├── inventory_action.py   # sd_add_to_cart, sd_sort_products
│   │   │   ├── cart_action.py        # sd_view_cart
│   │   │   └── checkout_action.py    # sd_checkout
│   │   └── phptravels/pages/         # (in progress)
│   │
│   └── sites/*/workflows/*.json      # Declarative workflow definitions
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

## Three-Layer Contract

```
  Layer         Location                    Responsibility
  ────────────  ──────────────────────────  ─────────────────────────────────────
  POM           poms/*/pages/               Selectors + raw page interactions only.
                                            No flow logic. No credentials.
                                            All interactive locators are cfg lists.

  Glue          stepper/sites/*/pages/      Wraps POM into a named Stepper behavior.
                                            One action, one job.
                                            Always injects page=page, resolver=resolver.

  Flow          stepper/sites/*/workflows/  Controls order, conditions, variables.
                *.json                      No selectors. No imperative logic.
```

**Dependency direction:** Flow → Glue → POM. Never reversed.

---

## Locator Pattern — cfg lists everywhere

Every interactive element in every POM is a **prioritised list of dicts**.
The list is the single source of truth — no parallel plain strings.

```python
class Locators:
    # Interactive inputs — cfg lists
    USERNAME_CFG = [
        {"label":       "Username",       "priority": 10},
        {"placeholder": "Username",       "priority": 20},
        {"id":          "username",       "priority": 30},
        {"css":         "#username",      "priority": 40},
    ]
    SUBMIT_CFG = [
        {"role": "button", "name": "Log in",  "priority": 10},
        {"role": "button", "name": "Sign in", "priority": 20},
        {"css":  ".cta-btn--primary",         "priority": 30},
    ]

    # Read-only state checks — plain strings are fine
    ERROR_MSG = "[data-test='error']"
    APP_LOGO  = ".app_logo"
```

**Rule:** If a method calls `fill()` or `click()`, the locator must be a cfg list.
If a method only reads (e.g. `query_selector` for text, `locator_count`), plain CSS is fine.

---

## SharedBasePage — resolver helpers

`poms/shared/base_page.py` contains all resolver-aware helpers.
Every site's `BasePage` inherits from it.

```
poms/shared/base_page.BasePage
    ├── _ordered_cfgs(cfgs)              sort by priority
    ├── _resolve_and_fill(cfg, value)    single cfg → fill
    ├── _resolve_and_click(cfg)          single cfg → click
    ├── _resolve_and_fill_any(cfgs, v)   try list in priority order → fill first match
    └── _resolve_and_click_any(cfgs)     try list in priority order → click first match

poms/openLibrary/pages/base_page.BasePage(SharedBasePage)
    └── adds: delays, open() with page_load_wait_ms

poms/saucedemo/pages/base_page.BasePage(SharedBasePage)
    └── thin wrapper — no additions needed

poms/phpTravels/pages/base_page.BasePage(SharedBasePage)
    └── thin wrapper — no additions needed
```

**Two operating modes** (determined by whether resolver is injected at construction):

| Mode | resolver= | Behaviour |
|---|---|---|
| driver-only | None | CSS/id extracted from cfg dict, called via driver |
| resolver-enhanced | ElementResolver instance | Full 10-stage cascade; falls back to driver on low confidence |

---

## Glue Layer — resolver injection contract

Every glue `_execute` method **must** pass `page=page, resolver=resolver` when constructing POMs:

```python
# CORRECT
login_page = LoginPage(driver, settings.base_url, settings.delays,
                       page=page, resolver=resolver)

# WRONG — resolver cascade never fires
login_page = LoginPage(driver, settings.base_url)
```

The `page` and `resolver` arguments arrive in `_execute(self, page, step, resolver, context)` — they are always available and must always be forwarded.

---

## Element Resolution Cascade

```
  cfg dict (role / label / placeholder / text / id / css / xpath)
         │
         ▼
  PHASE 1 — Deterministic (priority order)
  ──────────────────────────────────────────
  10  RoleResolver      (get_by_role)
  20  LabelResolver     (get_by_label)
  30  PlaceholderResolver
  40  TextResolver      (get_by_text)
  50  IdResolver
  60  CssResolver
  70  XPathResolver

  exactly 1 match → act
  0 or 2+ matches → Phase 2

  PHASE 2 — Semantic Filter
  ──────────────────────────
  Embed description (MiniLM-L6-v2) → cosine similarity
  score ≥ 0.80 → act
  2+ shortlisted → Phase 3

  PHASE 3 — AI Pick
  ──────────────────
  Groq → Gemini → Claude (cheapest first)
  confidence ≥ 0.70 → act
  all fail → top semantic result

  CONFIDENCE_AUTO   0.80   auto-act, no warning
  CONFIDENCE_WARN   0.50   warn but still act
```

---

## Site-Specific Actions

### OpenLibrary
| Action | Glue file | POM used |
|---|---|---|
| `ol_ensure_login` | `login_action.py` | `LoginPage` |
| `ol_collect_books` / `collect_items` | `search_page.py` | `BookSearchPage` |
| `ol_add_to_shelf` | `detail_page.py` | `BookDetailPage` |
| `ol_clear_reading_list` | `reading_list_action.py` | `ReadingListPage` + `BookDetailPage` |
| `ol_store_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_assert_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_ensure_count` | `reading_list_action.py` | `ReadingListPage` |

### SauceDemo
| Action | Glue file | POM used |
|---|---|---|
| `sd_login` | `login_action.py` | `LoginPage` |
| `sd_add_to_cart` | `inventory_action.py` | `InventoryPage` |
| `sd_sort_products` | `inventory_action.py` | `InventoryPage` |
| `sd_view_cart` | `cart_action.py` | `CartPage` |
| `sd_checkout` | `checkout_action.py` | `CartPage` + `CheckoutInfoPage` + `CheckoutOverviewPage` + `CheckoutCompletePage` |

---

## Adding a New Site

1. Create `poms/<site>/pages/base_page.py` inheriting `SharedBasePage`
2. Add POM files — all interactive locators as cfg lists
3. Create `stepper/sites/<site>/pages/` — one glue file per logical group
4. Pass `page=page, resolver=resolver` on every POM construction
5. Register actions in each glue file's `register()` classmethod

---

## Key Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| Strategy | ActionStrategy, Resolver, Reporter, Planner | Swap algorithms without changing caller |
| Template Method | ActionStrategy.execute() | Skeleton in base, steps in subclass |
| Factory + Registry | ActionRegistry | Register & create actions by name |
| Observer | StepRunner + StepObserver | Decouple reporting from execution |
| Chain of Responsibility | ElementResolver cascade | Try strategies in priority order |
| Adapter | PlaywrightDriver wraps Playwright Page | Isolate POMs from Playwright API |
| Dependency Inversion | All interfaces in shared/interfaces.py | POMs depend on abstractions only |
