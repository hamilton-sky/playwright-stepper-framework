# Stepper Framework — Architecture & Components

## Directory Structure

```
playwright-stepper-framework/
│
├── poms/                         # Pure Page Object Model layer
│   ├── shared/                   # Shared across all sites
│   │   ├── driver.py             # Playwright adapter (IBrowserDriver impl)
│   │   ├── interfaces.py         # POM contracts (IBrowserDriver, IElementHandle)
│   │   ├── base_page.py          # SharedBasePage — resolver helpers
│   │   ├── constants.py          # CONFIDENCE_AUTO / CONFIDENCE_WARN thresholds
│   │   ├── locator.py            # Shared locator utilities
│   │   └── performance.py        # Performance metrics
│   ├── openLibrary/              # OpenLibrary POMs
│   │   ├── config.py             # Settings loader (YAML + env vars)
│   │   └── pages/                # Pure POMs — selectors live here and nowhere else
│   │       ├── base_page.py
│   │       ├── login_page.py
│   │       ├── book_search_page.py   # collect_books_under_year → list[dict{url,year}]
│   │       ├── book_detail_page.py
│   │       └── reading_list_page.py
│   ├── saucedemo/                # SauceDemo POMs
│   │   ├── config.py
│   │   └── pages/
│   │       ├── base_page.py
│   │       ├── login_page.py
│   │       ├── inventory_page.py
│   │       ├── product_page.py
│   │       ├── cart_page.py
│   │       ├── checkout_info_page.py
│   │       ├── checkout_overview_page.py
│   │       └── checkout_complete_page.py
│   └── phpTravels/               # phpTravels POMs
│       ├── config.py
│       └── pages/
│           ├── base_page.py
│           ├── login_page.py
│           ├── home_page.py
│           ├── hotel_results_page.py
│           └── hotel_detail_page.py
│
├── stepper/                      # The Automation Engine
│   ├── main.py                   # Entry point — wires everything together
│   ├── pytest.ini                # asyncio_mode = auto, alluredir, log_cli settings
│   ├── engine/                   # Core framework modules
│   │   ├── interfaces.py         # Strategy/Observer abstractions + StepConfig
│   │   ├── actions/
│   │   │   ├── factory.py        # ActionRegistry (factory + registry pattern)
│   │   │   ├── strategies.py     # Navigate, Click, Fill, ForEach, Parallel,
│   │   │   │                     #   LoadTestData, etc.
│   │   │   └── sub_step_mixin.py # SubStepRunnerMixin — shared logic for nested steps
│   │   ├── ai/
│   │   │   ├── providers.py      # AI provider adapters (Groq, Gemini, Claude)
│   │   │   └── service.py        # Unified AI service interface
│   │   ├── browser/
│   │   │   ├── human_behaviour.py  # Per-action jitter, hover dwell, inter-step pauses
│   │   │   └── anti_detection.py   # Setup-time bot-fingerprint suppression
│   │   ├── healer/               # Self-healing element resolution
│   │   │   ├── ai_healer.py      # AI-powered locator repair
│   │   │   ├── annotator.py      # DOM annotation for healing context
│   │   │   ├── dom_snapshot.py   # DOM snapshot capture
│   │   │   └── interfaces.py     # Healer contracts
│   │   ├── resolvers/
│   │   │   ├── element_resolver.py   # Cascade orchestrator (det → semantic → AI)
│   │   │   ├── strategies.py         # 7 deterministic resolver strategies
│   │   │   └── ai_pick_resolver.py   # AI disambiguation (Groq → Gemini → Claude)
│   │   ├── runner/
│   │   │   ├── step_runner.py    # Execution loop (retry + observers)
│   │   │   ├── when_eval.py      # Conditional step evaluation
│   │   │   └── api.py            # Programmatic API
│   │   ├── planner/
│   │   │   ├── planner.py        # Claude AI planner / JSON file planner
│   │   │   ├── schema_extractor.py  # Extracts JSON schema from workflow
│   │   │   └── validator.py      # Validates planner output against schema
│   │   ├── reporter/
│   │   │   ├── reporters.py      # Console, JSON, Allure reporters
│   │   │   ├── test_report_manager.py
│   │   │   └── test_report_reporter.py
│   │   ├── pages/
│   │   │   ├── base_page_module.py  # PageModule ABC (site-specific actions)
│   │   │   ├── glue_action.py       # GlueAction base — enforces resolver injection
│   │   │   └── page_objects.py      # POM registry
│   │   └── utils.py
│   │
│   ├── bootstrap/                # Startup helpers extracted from main.py
│   │   ├── infra.py              # build_resolver(), launch_browser(), register_all_sites()
│   │   ├── reporting.py          # build_reporters(), serve_allure()
│   │   └── settings.py           # load_env(), load_settings_safe() → RunSettings
│   │
│   ├── sites/openlibrary/        # Site-specific action layer
│   │   ├── pages/
│   │   │   ├── search_page.py        # Registers ol_collect_books
│   │   │   ├── detail_page.py        # Registers ol_add_to_shelf
│   │   │   ├── login_action.py       # Registers ol_ensure_login
│   │   │   └── reading_list_action.py  # Registers ol_clear_reading_list,
│   │   │                               #   ol_store_count, ol_assert_count, ol_ensure_count
│   │   ├── register.py               # Auto-discovered by register_all_sites()
│   │   └── workflows/                # 10 JSON workflows
│   │       ├── ol_search_and_add.json
│   │       ├── ol_smoke_test.json
│   │       ├── ol_parallel_perf.json
│   │       ├── ol_data_driven.json   # Data-driven via --data flag
│   │       └── … (+ ol_add_only, ol_ensure_count, ol_regression_roundtrip,
│   │              ol_multi_author, ol_idempotency_test, login)
│   │
│   ├── sites/saucedemo/          # SauceDemo site integration
│   │   ├── pages/
│   │   │   ├── login_action.py       # Registers sd_login
│   │   │   ├── inventory_action.py   # Registers sd_add_to_cart, sd_sort_products
│   │   │   ├── cart_action.py        # Registers sd_view_cart
│   │   │   └── checkout_action.py    # Registers sd_checkout
│   │   ├── register.py               # Auto-discovered by register_all_sites()
│   │   └── workflows/
│   │       ├── sd_happy_path.json
│   │       ├── sd_multi_product.json
│   │       ├── sd_smoke_test.json
│   │       ├── sd_heal_test.json     # Self-healing locator test
│   │       └── sd_full_heal_flow.json  # Full self-healing demonstration flow
│   │
│   ├── sites/phptravels/         # phpTravels site integration (fully wired)
│   │   ├── pages/
│   │   │   ├── login_action.py       # Registers pt_login
│   │   │   ├── hotel_search_action.py  # Registers pt_search_hotels
│   │   │   ├── hotel_results_action.py # Registers pt_select_hotel
│   │   │   └── hotel_detail_action.py  # Registers pt_book_hotel
│   │   ├── register.py               # Auto-discovered by register_all_sites()
│   │   └── workflows/
│   │       └── hotel_booking.json
│   │
│   ├── tests/                    # Stepper engine test suite
│   │   ├── conftest.py           # --headed flag registration
│   │   └── test_workflow.py      # Workflow integration tests
│   │
│   ├── models/
│   │   └── all-MiniLM-L6-v2/    # Pre-trained semantic embedding model
│   ├── artifacts/                # Runtime cache (storage_state.json, screenshots)
│   └── reports/                  # Output: allure-results/, per-run folders
│
├── exam/                         # Exam test layer
│   ├── conftest.py
│   ├── flows.py                  # Orchestrate POMs into test flows
│   ├── pytest.ini
│   └── tests/
│       └── test_openlibrary_exam.py
│
└── requirements.txt              # All dependencies (install from repo root)
```

---

## Overall Data Flow

```
  CLI / pytest
      │
      │  --workflow / --task / --vars / --data
      ▼
┌─────────────┐        ┌──────────────────────────────────┐
│  main.py    │──────▶ │  Planner                         │
│  (entry)    │        │  ─────────────────────────────── │
└─────────────┘        │  JSON file  ──┐                  │
                       │  Claude AI  ──┴─▶ [StepConfig]   │
                       └──────────────────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────┐
                       │  Infrastructure Setup            │
                       │  ──────────────────────────────  │
                       │  • Load Settings (YAML + env)    │
                       │  • Build ElementResolver         │
                       │  • Build ActionRegistry          │
                       │  • Init Reporters                │
                       │  • Launch Playwright browser     │
                       └──────────────┬───────────────────┘
                                      │
                                      ▼
                       ┌──────────────────────────────────┐
                       │  StepRunner  (execution loop)    │
                       │  ──────────────────────────────  │
                       │  for each StepConfig:            │
                       │    1. Eval 'when' condition       │
                       │    2. Lookup ActionStrategy      │
                       │    3. Retry loop                 │
                       │       └▶ action.execute()        │
                       │    4. Notify observers           │
                       │    5. Record StepResult          │
                       │    6. continue_on_failure?       │
                       │       yes → warn + continue      │
                       │       no  → hard-stop            │
                       └──────┬───────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐
    │  Reporters  │   │  Observers   │   │  ExecutionCtx   │
    │  ─────────  │   │  ──────────  │   │  ─────────────  │
    │  Console    │   │  Logging     │   │  collected_items │
    │  JSON       │   │  Callbacks   │   │  extracted_data │
    │  Allure     │   │              │   │  counts{}       │
    │  HTML report│   │              │   │                 │
    └─────────────┘   └──────────────┘   └─────────────────┘
```

---

## Element Resolution Cascade

```
  StepConfig.element  (dict of hints: role, text, css, xpath, …)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │  ElementResolver                             │
  │                                              │
  │  PHASE 1 — Deterministic (priority order)   │
  │  ─────────────────────────────────────────  │
  │  10  RoleResolver      (get_by_role)         │
  │  20  LabelResolver     (get_by_label)        │
  │  30  PlaceholderResolver                     │
  │  40  TextResolver      (get_by_text)         │
  │  50  IdResolver                              │
  │  60  CssResolver                             │
  │  70  XPathResolver                           │
  │                                              │
  │  exactly 1 match? ──────────────────▶ DONE  │
  │  0 or 2+ matches?  ─────────────────────┐   │
  └─────────────────────────────────────────┼───┘
                                            │
                                            ▼
  ┌──────────────────────────────────────────────┐
  │  PHASE 2 — Semantic Filter                   │
  │  ─────────────────────────────────────────  │
  │  • Embed step description (MiniLM-L6-v2)    │
  │  • Score each candidate by cosine sim       │
  │  • Keep candidates with score ≥ 0.80        │
  │                                              │
  │  1 shortlisted? ────────────────────▶ DONE  │
  │  2+ shortlisted? ───────────────────────┐   │
  │  0 shortlisted?  ──▶ Visual AI fallback │   │
  └─────────────────────────────────────────┼───┘
                                            │
                                            ▼
  ┌──────────────────────────────────────────────┐
  │  PHASE 3 — AI Pick                           │
  │  ─────────────────────────────────────────  │
  │  Provider chain (cheapest first):            │
  │    1. Groq                                   │
  │    2. Gemini                                 │
  │    3. Claude                                 │
  │                                              │
  │  "Which candidate best matches the step?"   │
  │  confidence ≥ 0.70 ─────────────────▶ DONE  │
  │  all fail ──────────────────▶ top semantic  │
  └──────────────────────────────────────────────┘

  CONFIDENCE THRESHOLDS
  ─────────────────────
  CONFIDENCE_AUTO        0.80   auto-act, no warning
  CONFIDENCE_WARN        0.50   warn but still act
  CONFIDENCE_SEMANTIC    0.80   semantic filter cutoff
  CONFIDENCE_AI_PICK     0.70   AI picker acceptance
  CONFIDENCE_DESCRIPTION 0.40   description fallback minimum
```

---

## Action Execution (Template Method Pattern)

```
  ActionRegistry.create("action_name")
          │
          ▼
  ┌──────────────────────────────────────────┐
  │  ActionStrategy.execute()               │
  │  ──────────────────────────────────────  │
  │                                          │
  │  1.  pre_execute(page, step)            │
  │      └─ override for setup              │
  │                                          │
  │  2.  _execute(page, step, resolver)     │  ◀── concrete impl
  │      └─ resolve element if needed       │
  │         └─ act on element               │
  │                                          │
  │  3.  post_execute(page, step, result)  │
  │      └─ screenshot, teardown            │
  │                                          │
  │  Returns: StepResult                    │
  │  ─────────────────────────────────────  │
  │  status:       passed|failed|skip|warn  │
  │  confidence:   resolver confidence      │
  │  duration_ms:  execution time           │
  │  screenshot:   file path                │
  │  output:       dict (step-produced data │
  │                saved to results.json)   │
  └──────────────────────────────────────────┘

  BUILT-IN ACTIONS
  ────────────────
  navigate            → goto(url), wait_for_load_state
  click               → resolve element → click()
  fill                → resolve element → fill(text)
  hover               → resolve element → hover()
  select              → resolve element → selectOption()
  screenshot          → page.screenshot()
  wait                → asyncio.sleep / wait_for_selector
  store_count         → locator.count() → context.counts[key]
  assert_count        → context.counts[key] vs expected value
  extract_data        → collect elements → context.extracted_data
  paginate            → loop pages, accumulate items → context.paginated_data
  for_each_item       → iterate context.collected_items, run sub-steps
  ensure_login        → delegate to site-specific login action
  measure_performance → capture performance metrics
  visual_compare      → screenshot diff against stored baseline (pixel-level)
  parallel            → run read-only actions concurrently in separate tabs
  run_workflow        → nested sub-workflow execution
  load_test_data      → load JSON test-data file → context.test_data

  SITE-SPECIFIC ACTIONS (OpenLibrary)
  ────────────────────────────────────
  ol_ensure_login       → LoginPage.is_session_live() → fill + submit if needed
  ol_collect_books      → BookSearchPage.collect_books() → context.collected_items
                          list[dict{url, year}] — also written to StepResult.output
                          limit: step.extra["limit"] or context.counts["gap"] or 5
  ol_add_to_shelf       → BookDetailPage.add_to_reading_list() per collected item
                          StepResult.output = {books: [{url, year, shelf}, …]}
  ol_clear_reading_list → ReadingListPage.clear() (removes all books)
  ol_store_count        → ReadingListPage.count() → context[context_key]
  ol_assert_count       → assert context count == expected (delta or absolute)
  ol_ensure_count       → count shelf, store gap in context if top-up needed
                          flow controls collect / add / assert via when-guards

  SITE-SPECIFIC ACTIONS (SauceDemo)
  ───────────────────────────────────
  sd_login          → LoginPage.login() → fills credentials, submits
  sd_add_to_cart    → InventoryPage.add_products() → adds named products to cart
  sd_sort_products  → InventoryPage.sort() → sets dropdown sort order
  sd_view_cart      → CartPage.open() → navigates to cart, reads item list
  sd_checkout       → CartPage → CheckoutInfoPage → CheckoutOverviewPage → CompletePage

  STEP-LEVEL CONTROLS (resolved at plan time by JsonFilePlanner)
  ──────────────────────────────────────────────────────────────
  when:                  skip step if condition is false
  retry: N               retry on failure up to N times (retry_delay_ms between)
  continue_on_failure:   true  → warn + continue on failure
                         false → hard-stop on failure (default)

  FLOW-LEVEL DEFAULTS (pass down to all steps, step always wins)
  ──────────────────────────────────────────────────────────────
  continue_on_failure: true   → all steps soft-fail unless they override to false
  variables: {}               → substituted into all step values at plan time

  THREE-LAYER CONTRACT
  ─────────────────────
  POM   (poms/*/pages/)          owns selectors + raw page interactions
  Glue  (sites/*/pages/)         wraps POM into named behavior — one action, one job
  Flow  (workflows/*.json)       controls order, conditions, variables — no selectors
```

---

## Configuration Loading

```
  DEFAULTS (hardcoded in config.py)
         │
         ▼  override
  config.yaml  (optional — falls back to defaults if absent)
         │
         ▼  override
  Environment variables  (OPENLIBRARY_*)
         │
         ▼
  Settings (frozen dataclass)
  ──────────────────────────
  base_url            "https://openlibrary.org"
  headless            True
  slow_mo_ms          300
  browser             "chromium"
  username / password credentials
  screenshots_dir     Path
  storage_state_path  Path  (session cache)
  performance_output  Path
  logs_dir            Path
  delays              Delays (page_load_wait_ms, …)
  use_visual_ai       bool
  login_url           str
  max_login_attempts  int
  shelf_paths         tuple[str]
```

---

## Reporting & Observer Chain

```
                    StepRunner
                        │
              ┌─────────┴──────────┐
              │                    │
              ▼                    ▼
       REPORTER CHAIN        OBSERVER CHAIN
       (Strategy)            (Observer)

  ┌──────────────────┐   ┌──────────────────┐
  │ ConsoleReporter  │   │ LoggingObserver  │
  │ └ stdout summary │   │ └ Python logger  │
  ├──────────────────┤   ├──────────────────┤
  │ JsonReporter     │   │ CallbackObserver │
  │ └ report.json    │   │ └ custom hooks   │
  ├──────────────────┤   └──────────────────┘
  │ TestReportRep.   │
  │ └ test-<label>/  │
  │   ├ index.html   │
  │   ├ logs/run.log │
  │   └ artifacts/   │
  ├──────────────────┤
  │ AllureReporter   │
  │ └ allure-results/│
  └──────────────────┘

  REPORTER CONTRACT           OBSERVER CONTRACT
  ─────────────────           ────────────────
  start_suite(name)           on_step_start(idx, step)
  record_step(result)         on_step_done(idx, result)
  finish_suite() → path       on_log(message, level)
```

---

## Workflow Example: "Search & Add" End-to-End

```
  ol_search_and_add.json
  ──────────────────────
  Variables: query="Dune"  max_year=1980  limit=5

  Step 1  ol_ensure_login
          └─▶ LoginPage.is_session_live() → already logged in, skip
              or  LoginPage.open() → fill_username → fill_password → submit

  Step 2  ol_clear_reading_list
          └─▶ ReadingListPage.clear() → shelf is empty

  Step 3  ol_store_count
          └─▶ count shelf items
          └─▶ context.counts["count_before"] = 0

  Step 4  ol_collect_books
          extra: { query:"Dune", filter:{year_max:1980}, limit:5 }
          └─▶ BookSearchPage.search("Dune")
          └─▶ BookSearchPage.collect_books_under_year(1980, limit=5)
          └─▶ context.collected_items = [{url, year}, …]  (list[dict])
          └─▶ StepResult.output = {items: [{url, year}, …]}

  Step 5  ol_add_to_shelf
          └─▶ for item in context.collected_items:
                  navigate(item["url"]) → click shelf button → screenshot()
          └─▶ StepResult.output = {books: [{url, year, shelf}, …]}

  Step 6  ol_assert_count
          extra: { delta: 5 }
          └─▶ new_count == context.counts["count_before"] + 5
          └─▶ PASS / hard-stop on FAIL

  Output
  ──────
  Console        6 / 6 passed
  report.json    structured step results
  test-<label>/  index.html + logs + screenshots
  allure-results allure serve
```

---

## Workflow Example: "Top-Up" with Context-Driven when-guards

```
  ol_ensure_count.json
  ────────────────────
  Variables: target_count=5  query="Dune"  max_year=1980

  Step 1  ol_ensure_login        → always runs

  Step 2  ol_ensure_count
          extra: { target_count: 5 }
          IF current >= 5  → pass, gap NOT stored → steps 3-5 skip
          IF current < 5   → gap = 5 - current stored in context.counts["gap"]

  Step 3  ol_collect_books       when: context_key_exists: gap
          limit read from context.counts["gap"] (no limit in extra)
          └─▶ context.collected_items = [url1 … urlN]

  Step 4  ol_add_to_shelf        when: context_key_exists: collected_items
          └─▶ adds collected books to shelf

  Step 5  ol_assert_count        when: context_key_exists: gap
          extra: { expected_count: 5 }
          └─▶ verifies final count == target

  Context as signal: ol_ensure_count produces "gap", when-guards consume it.
  Flow controls everything. No action calls another action.
```

---

## Design Patterns Summary

```
  Pattern              Where                         Purpose
  ───────────────────  ────────────────────────────  ──────────────────────────────
  Strategy             ActionStrategy, Resolver,      Swap algorithms without
                       Reporter, Planner              changing caller code
  Template Method      ActionStrategy.execute()       Skeleton in base, steps in sub
  Factory + Registry   ActionRegistry                 Register & create by name
  Observer             StepRunner + StepObserver      Decouple reporting from exec
  Chain of Resp.       ElementResolver cascade        Try strategies in order
  Adapter              PlaywrightDriver wraps Page    Isolate from Playwright API
  Dependency Inversion All interfaces                 Depend on abstractions only
```
