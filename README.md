# OpenLibrary Automation — Stepper Framework

End-to-end automation framework for [openlibrary.org](https://openlibrary.org) built with Playwright + Python.

Implements the full exam specification using a clean POM layer, then extends it with a JSON-driven Stepper engine that adds retry, smart locators, conditional flows, and multi-site orchestration — all without touching Python code.

> **Examiner**: see [SUBMISSION.md](SUBMISSION.md) for a SOLID walkthrough with file references and an architectural patterns guide.

---

## Quick Start

### 1. Install dependencies

```bash
# from repo root
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
# Fill in:
# OPENLIBRARY_USERNAME=your@email.com
# OPENLIBRARY_PASSWORD=yourpassword
```

### 3. Run

**Option A — Exam pytest suite:**
```bash
cd exam
pytest tests/ -v
```

**Option B — Stepper JSON workflow:**
```bash
cd stepper
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json
```

**Option C — Headed browser (watch the automation):**
```bash
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json --show
```

---

# Part I — Exam Solution (POM Approach)

## What the exam required

Four orchestration functions, clean POM separation, and data-driven test cases.

```
exam/
├── flows.py                      ← 4 required functions
├── conftest.py                   ← fixtures, parametrization, auth
├── pytest.ini
└── tests/
    └── test_openlibrary_exam.py  ← TestOpenLibraryExam: search → add → assert → perf
```

## Four Required Functions

All live in `exam/flows.py` and delegate directly to `poms/` classes:

```python
async def search_books_by_title_under_year(
    page, query: str, max_year: int, limit: int = 5
) -> list[str]:
    """Search OpenLibrary, filter by publication year, paginate until limit reached."""
    driver = PlaywrightDriver(page)
    search_page = BookSearchPage(driver, settings.base_url, settings.delays)
    await search_page.search(query)
    return await search_page.collect_books_under_year(max_year, limit)


async def add_books_to_reading_list(page, urls: list[str]) -> None:
    """Open each book URL and add to Want to Read / Already Read + screenshot."""
    driver = PlaywrightDriver(page)
    for idx, url in enumerate(urls, start=1):
        detail = BookDetailPage(driver, settings.base_url, book_url=url, delays=settings.delays)
        await detail.open()
        await detail.add_to_reading_list()
        await screenshot_mgr.capture(f"book_{idx}_{slug}")


async def assert_reading_list_count(page, expected_count: int) -> None:
    """Navigate to both shelves, count books, assert against expected."""
    driver = PlaywrightDriver(page)
    reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
    actual = await reading_list.get_book_count()
    assert actual == expected_count, f"Expected {expected_count} books, got {actual}"


async def measure_page_performance(page, url: str, threshold_ms: int) -> dict:
    """Measure first_paint_ms, dom_content_loaded_ms, load_time_ms."""
    driver = PlaywrightDriver(page)
    return await _measure_perf(driver, url, threshold_ms, output_path=settings.performance_output)
```

## Data-Driven Test Cases

Test parameters live in `poms/openLibrary/data/testdata.json` and are automatically parametrized
via `pytest_generate_tests` in `conftest.py` — no test code changes needed to add a new case:

```json
[
  { "query": "Dune",               "max_year": 1980, "limit": 5 },
  { "query": "Foundation",         "max_year": 1990, "limit": 3 },
  { "query": "1984",               "max_year": 1950, "limit": 2 },
  { "query": "Pride and Prejudice","max_year": 1820, "limit": 4 }
]
```

```bash
pytest tests/ -v              # default case (index 0)
pytest tests/ -v --case 2     # run case at index 2
pytest tests/ -v --all-cases  # run all 4 cases
```

## Running the Exam Suite

**Authentication**: first run logs in and saves `artifacts/storage_state.json`.
Subsequent runs load saved cookies — no re-login.

```bash
cd exam

pytest tests/ -v
pytest tests/ -v --headed                             # watch the browser
pytest tests/ -v --case 1                             # specific test case
pytest tests/ -v --all-cases                          # all parametrised cases
pytest tests/ -v --alluredir=reports/allure-results   # generate Allure report
allure serve reports/allure-results
```

---

# Where Plain POM Reaches Its Limits

The exam layer is clean and correct. At scale, the friction points are:

- **No built-in retry** — a flaky network click fails the whole test; recovery requires manual `try/except`
- **Orchestration accumulates in Python** — conditional branching, step sequencing, and
  context-passing between functions all live in imperative code
- **Intermediate values don't flow declaratively** — results pass through a `_shared_results` dict;
  later steps can't reference earlier results by name in configuration
- **No composable sub-flows** — reusing a login sequence across tests means copy-paste or a helper
  with a growing parameter list
- **No parallel step execution** — running three pages concurrently requires asyncio boilerplate
  in the test itself
- **Extending to a new site** means new flow functions, new fixtures, new conftest entries

These aren't bugs — they're the natural ceiling of the pattern. The Stepper externalises the
orchestration engine so the Python layer stays thin.

---

# Part II — Stepper Framework

```bash
cd stepper 

# run one case (default: index 0)
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json

# run a specific case by index
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json --case 2

# run all cases
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json --all-cases

```



## Three-Layer Architecture

```
  Layer         Location                      Responsibility
  ────────────  ────────────────────────────  ──────────────────────────────────────────
  Flow (JSON)   stepper/sites/*/workflows/    Controls order, conditions, variables.
                                              No selectors. No imperative logic.

  Glue          stepper/sites/*/pages/        Wraps POM into a named Stepper action.
                                              One action, one job.
                                              Always injects page=page, resolver=resolver.

  POM           poms/*/pages/                 Selectors + raw page interactions only.
                                              No flow logic. No credentials.
                                              All interactive locators are cfg lists.
```

**Dependency direction is one-way: Flow → Glue → POM. Never reversed.**

## Architecture in One Diagram

```
JSON Workflow          Stepper Engine              POM Layer               Browser
──────────────         ──────────────              ─────────               ───────
{                      StepRunner                  BookSearchPage
  "action":       →    ActionFactory.create()  →   .search()           →   Playwright
  "ol_collect_         OLCollectBooksAction         .collect_books()        page.fill()
   books",             ._execute()                                          page.click()
  "extra": {                                        BookDetailPage
    "query":           (retries, screenshots,       .add_to_reading_list()
    "Dune"             reporting all handled    →   .remove_from_shelf()
  }                     by the engine)
}                                                   ReadingListPage
                                                    .get_book_count()
                                                    .collect_all_book_urls()

   WHAT to do            HOW to run it            WHERE elements are        DO it
```

> JSON contains action names and parameters only — never CSS selectors or XPaths.
> All element knowledge lives exclusively in the POM `Locators` inner classes.

## Exam Layer vs Stepper — Side by Side

| Capability | Exam layer | Stepper |
|---|---|---|
| Data-driven test cases | `testdata.json` → `pytest_generate_tests` | `variables{}` in workflow JSON |
| Runtime context between steps | Python `_shared_results` dict | `{{gap}}`, `{{count}}` resolved at execution time |
| Conditional execution | Python `if` in test body | `when:` guard — declarative, zero Python |
| Retry per step | Manual `try/except` | `retry`, `retry_delay_ms` per step |
| Sub-workflow composition | Copy-paste helpers | `run_workflow` action |
| Parallel steps | `asyncio` boilerplate in test | `parallel` action |
| Screenshots / reports | Manual calls | Observer fires automatically after every step |

---

## Smart Locators — Resolver Cascade

The `ElementResolver` tries strategies in resilience order, stopping at the first confident match:

```
  cfg dict  (role / label / placeholder / text / id / css / xpath)
       │
       ▼
  PHASE 1 — Deterministic
  ──────────────────────────────────────────────────────────────────
  Priority  Strategy             Playwright call           Confidence
  ────────  ───────────────────  ───────────────────────── ──────────
  10        RoleResolver         get_by_role(role, name=n) 0.95
  20        LabelResolver        get_by_label(label)       0.93
  30        PlaceholderResolver  get_by_placeholder(ph)    0.90
  40        TextResolver         get_by_text(text)         0.85
  50        IdResolver           locator(f"#{id}")         0.82
  60        CssResolver          locator(css)              0.75
  70        XPathResolver        locator(f"xpath={x}")     0.70

  Exactly 1 match → act immediately
  0 or 2+ matches → Phase 2

  PHASE 2 — Semantic Filter
  ──────────────────────────────────────────────────────────────────
  Model:   MiniLM-L6-v2 (sentence-transformers, bundled locally)
  Method:  embed cfg description → cosine similarity vs. element text
  score ≥ 0.80 and exactly 1 match → act
  2+ shortlisted at threshold    → Phase 3

  PHASE 3 — AI Pick
  ──────────────────────────────────────────────────────────────────
  Provider chain (cheapest first):  Groq → Gemini → Claude
  confidence ≥ 0.70 → act
  all providers fail → fall back to top semantic result
```

**Why this matters:** CSS selectors break on class renames. ARIA roles and labels survive redesigns.
The cascade tries the most stable locator first and falls back gracefully — no test rewrite needed
when the UI changes.

---

## Step Controls

Every step supports these optional fields:

| Field | Default | Effect |
|---|---|---|
| `when` | — | Skip step if condition is false |
| `retry` | `0` | Retry on failure up to N times |
| `retry_delay_ms` | `1000` | Milliseconds between retries |
| `continue_on_failure` | `false` | `true` → warn and continue; `false` → hard-stop |
| `extra` | — | Arbitrary config passed to action; supports `{{var}}` substitution |
| `read_only` | `false` | For `parallel` steps: `true` → run in shared read-only tab; `false` → separate tab with fresh state |
| `screenshot_on` | `failure` | `always` → capture after every attempt; `failure` → capture only on final failure |


### `when` condition reference

| Condition | Syntax | Notes |
|---|---|---|
| `context_equals` | `{ "key": "k", "value": 0 }` | Exact match |
| `context_key_exists` | `"key_name"` | True if key is set and non-empty |
| `context_greater_than` | `{ "key": "gap", "value": 0 }` | Numeric `>` |
| `context_less_than` | `{ "key": "count", "value": 10 }` | Numeric `<` |
| `context_between` | `{ "key": "count", "min": 2, "max": 8 }` | Inclusive range |
| `url_contains` | `"/account/login"` | Current page URL |
| `element_exists` | `"input[name='q']"` | Live DOM check |
| `not` | `<any condition>` | Invert |
| `all` | `[<cond>, ...]` | AND short-circuit |
| `any` | `[<cond>, ...]` | OR short-circuit |


### Flow-level defaults

Declare once at the top; all steps inherit unless they override:

```json
{
  "continue_on_failure": true,
  
  "steps": [
    { "action": "ol_ensure_login", "continue_on_failure": false },
    { "action": "screenshot" }
  ]
}
```

Step always wins over flow. `ol_ensure_login` hard-stops; `screenshot` soft-fails.

---

## Runtime Variable Resolution

`variables{}` in JSON are substituted at **plan time** by `JsonFilePlanner`.
Context values set by earlier steps are substituted at **runtime** by `StepRunner` —
so `{{gap}}` resolves to the integer stored by `ol_ensure_count` at the moment the step runs:

```json
{ "action": "ol_collect_books",
  "when":  { "context_greater_than": { "key": "gap", "value": 0 } },
  "extra": { "limit": "{{gap}}" }
}
```

A pure `"{{key}}"` reference preserves the original type (int, bool).
Mixed strings like `"page_{{n}}"` are string-substituted.

Override any variable at runtime without touching the JSON:

```bash
cd stepper
python main.py --workflow sites/openlibrary/workflows/ol_regression_roundtrip.json \
  --vars '{"query":"Asimov","max_year":1960,"limit":2}'
```
# run one case (default: index 0)
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json

# run a specific case by index
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json --case 2

# run all cases
pytest tests/ -v --workflow ol_search_and_add.json --data ../poms/openLibrary/data/testdata.json --all-cases



---

## Showcase Workflows

Twelve ready-to-run JSON workflows demonstrating every engine capability:

**OpenLibrary (9 workflows)**

| Workflow | What it showcases | Command (run from `stepper/`) |
|---|---|---|
| `ol_search_and_add.json` | Main exam flow: clear → search → add → assert | `python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json` |
| `ol_add_only.json` | Idempotent append — no clear step | `python main.py --workflow sites/openlibrary/workflows/ol_add_only.json` |
| `ol_ensure_count.json` | Top-up to target N via `when` + `{{gap}}` | `python main.py --workflow sites/openlibrary/workflows/ol_ensure_count.json` |
| `ol_regression_roundtrip.json` | Full lifecycle + delta and absolute asserts | `python main.py --workflow sites/openlibrary/workflows/ol_regression_roundtrip.json` |
| `ol_multi_author.json` | Two-query sequential composition (Dune + Tolkien) | `python main.py --workflow sites/openlibrary/workflows/ol_multi_author.json` |
| `ol_parallel_perf.json` | Three pages benchmarked concurrently in separate tabs | `python main.py --workflow sites/openlibrary/workflows/ol_parallel_perf.json` |
| `ol_smoke_test.json` | `when`-guarded + `continue_on_failure` soft-fail | `python main.py --workflow sites/openlibrary/workflows/ol_smoke_test.json` |
| `ol_idempotency_test.json` | Add same books twice → count must not grow | `python main.py --workflow sites/openlibrary/workflows/ol_idempotency_test.json` |
| `login.json` | Generic reusable login subflow | `python main.py --workflow sites/openlibrary/workflows/login.json` |

**SauceDemo (3 workflows)**

| Workflow | What it showcases | Command (run from `stepper/`) |
|---|---|---|
| `sd_happy_path.json` | Login → add to cart → checkout | `python main.py --workflow sites/saucedemo/workflows/sd_happy_path.json` |
| `sd_multi_product.json` | Add multiple products, verify cart | `python main.py --workflow sites/saucedemo/workflows/sd_multi_product.json` |
| `sd_smoke_test.json` | Smoke check with `continue_on_failure` | `python main.py --workflow sites/saucedemo/workflows/sd_smoke_test.json` |

---

## Available Stepper Actions

| Action | Description |
|---|---|
| `ol_ensure_login` | `LoginPage.is_session_live()` → fill + submit if needed |
| `ol_collect_books` | Search + filter by year + paginate → fills `context.collected_items`; supports `"{{gap}}"` runtime limit |
| `ol_add_to_shelf` | Add each collected book to a reading shelf + screenshot |
| `ol_clear_reading_list` | Remove all books from want-to-read shelf |
| `ol_store_count` | Count books across both shelves → stores in `context` |
| `ol_assert_count` | Assert count equals `expected_count` or `count_before + delta` |
| `ol_ensure_count` | Count shelf, store `gap` in context if top-up needed |
| `sd_login` | SauceDemo login — fills credentials, submits |
| `sd_add_to_cart` | Add named products to cart by title |
| `sd_sort_products` | Set inventory sort order (az, za, lohi, hilo) |
| `sd_view_cart` | Navigate to cart, read item list into context |
| `sd_checkout` | Full checkout flow: info → overview → confirm |
| `navigate` | Go to URL |
| `click` | Click element via resolver cascade |
| `fill` | Type into input + press Enter |
| `hover` | Hover over element (triggers CSS `:hover` menus) |
| `select` | Select from `<select>` dropdown by label, index, or value |
| `screenshot` | Capture screenshot to file |
| `wait` | Wait for selector, URL fragment, or fixed seconds |
| `extract_data` | Scrape DOM data into `context.extracted_data` |
| `paginate` | Loop pages, accumulate results → `context.paginated_data` |
| `for_each_item` | Loop over `context.collected_items`, run sub-steps per item |
| `store_count` | Count elements via CSS selectors, store in `context` |
| `assert_count` | Assert element count matches expected (CSS or context source) |
| `measure_performance` | Collect `first_paint_ms`, `dom_content_loaded_ms`, `load_time_ms` |
| `visual_compare` | Pixel-level screenshot diff against stored baseline |
| `ensure_login` | Generic login subflow — accepts `login_steps` list in config |
| `run_workflow` | Execute a sub-workflow JSON file then return to parent flow |
| `parallel` | Run multiple `read_only` sub-steps concurrently in separate tabs |

---

# Design Principles

| Principle | Implementation |
|---|---|
| **SRP** | Each class has one job: `StepRunner` runs steps, `ElementResolver` finds elements, `BookSearchPage` knows the search page |
| **OCP** | Add a new site: create a folder + register. Add a new action: subclass `ActionStrategy` + register. Zero edits to existing code |
| **DIP** | `StepRunner` depends on `ActionFactory` interface, never on `OLCollectBooksAction` directly |
| **POM** | All selectors live in `Locators` inner classes. JSON and glue layers never duplicate selector strings |
| **Data-Driven** | Workflow logic is JSON; parameters are variables; env overrides config; test data separates from code |

---

# Reports & Artifacts

| Artifact | Location | Generated by |
|---|---|---|
| Allure report | `reports/allure-results/` | `AllureReporter` |
| JSON report | `report.json` | `JsonReporter` |
| Test run folder | `reports/<timestamp>_<name>/` | `TestReportReporter` |
| Screenshots | `reports/<run>/screenshots/` | Auto after each step |
| Run log | `reports/<run>/logs/run.log` | File log handler |
| Performance data | `artifacts/performance.json` | `measure_performance` action |

```bash
allure serve reports/allure-results
```

---

# Project Structure

```
playwright-stepper-framework/
│
├── poms/                             # Pure Page Object Model layer
│   ├── shared/                       # Shared across ALL sites
│   │   ├── interfaces.py             # IBrowserDriver, IElementHandle, Delays (DIP contracts)
│   │   ├── driver.py                 # PlaywrightDriver — implements IBrowserDriver
│   │   ├── base_page.py              # SharedBasePage — resolver helpers
│   │   ├── constants.py              # CONFIDENCE_AUTO / CONFIDENCE_WARN — single source of truth
│   │   └── performance.py            # measure_page_performance() — raw timing via JS API
│   ├── openLibrary/
│   │   ├── config.py                 # 3-tier settings: defaults → config.yaml → ENV
│   │   ├── pages/
│   │   │   ├── base_page.py          # BasePage: open(), navigate(), delay helpers
│   │   │   ├── login_page.py         # LoginPage: selectors + is_session_live()
│   │   │   ├── book_search_page.py   # search(), collect_books_under_year() + pagination
│   │   │   ├── book_detail_page.py   # add_to_reading_list(), remove_from_shelf()
│   │   │   └── reading_list_page.py  # get_book_count(), collect_all_book_urls()
│   │   ├── utils/
│   │   │   ├── book_filter.py        # extract_year_from_text(), is_under_year()
│   │   │   ├── shelf.py              # SHELF_LABEL_WANT / SHELF_LABEL_ALREADY constants
│   │   │   └── screenshot.py         # ScreenshotManager helper
│   │   └── data/
│   │       └── testdata.json         # Parametrised test cases (query, max_year, limit)
│   ├── saucedemo/
│   │   ├── config.py                 # SauceDemo settings
│   │   ├── pages/
│   │   │   ├── base_page.py
│   │   │   ├── login_page.py
│   │   │   ├── inventory_page.py
│   │   │   ├── product_page.py
│   │   │   ├── cart_page.py
│   │   │   ├── checkout_info_page.py
│   │   │   ├── checkout_overview_page.py
│   │   │   └── checkout_complete_page.py
│   │   └── data/
│   │       └── testdata.json
│   └── phpTravels/                   # phpTravels POMs [scaffolded — not integrated; POM layer only, no glue or workflows]
│
├── exam/                             # Pytest exam suite — calls poms/ directly
│   ├── flows.py                      # 4 exam function signatures (orchestration layer)
│   ├── conftest.py                   # Fixtures, parametrization, auth via storage_state.json
│   ├── pytest.ini                    # asyncio_mode = auto
│   └── tests/
│       └── test_openlibrary_exam.py  # TestOpenLibraryExam: search → add → assert → perf
│
├── stepper/                          # Stepper framework + site integrations
│   ├── main.py                       # DIP root — wires registry, resolver, runner, reporter
│   ├── engine/                       # Core engine (site-agnostic)
│   │   ├── interfaces.py             # StepConfig, StepResult, ExecutionContext (all abstract)
│   │   ├── actions/
│   │   │   ├── factory.py            # ActionRegistry + build_default_registry()
│   │   │   ├── strategies.py         # navigate, click, fill, hover, select, screenshot,
│   │   │   │                         #   wait, store_count, assert_count, for_each_item,
│   │   │   │                         #   extract_data, paginate, ensure_login,
│   │   │   │                         #   measure_performance, visual_compare,
│   │   │   │                         #   run_workflow, parallel
│   │   │   └── sub_step_mixin.py     # SubStepRunnerMixin — shared nested-step logic
│   │   ├── resolvers/
│   │   │   ├── element_resolver.py   # Cascade executor + DefaultResolverFactory
│   │   │   ├── strategies.py         # Role → Label → Placeholder → Text → Id → Css → XPath
│   │   │   └── ai_pick_resolver.py   # AI disambiguation (Groq → Gemini → Claude)
│   │   ├── runner/
│   │   │   ├── step_runner.py        # Execution loop, retry, observer notifications
│   │   │   ├── api.py                # StepperSession + run_steps() public API
│   │   │   └── when_eval.py          # Condition evaluator: context_equals, url_contains,
│   │   │                             #   element_exists, context_key_exists, not/all/any
│   │   ├── reporter/
│   │   │   ├── reporters.py          # CompositeReporter, ConsoleReporter, JsonReporter,
│   │   │   │                         #   AllureReporter, TestReportReporter
│   │   │   └── test_report_reporter.py
│   │   ├── pages/
│   │   │   ├── base_page_module.py   # PageModule ABC
│   │   │   ├── glue_action.py        # GlueAction base — enforces resolver injection
│   │   │   └── page_objects.py       # POM registry
│   │   └── planner/
│   │       └── planner.py            # JsonFilePlanner (loads JSON) + ClaudePlanner (AI)
│   │
│   ├── sites/openlibrary/
│   │   ├── pages/                    # Glue layer — wires POMs into Stepper actions
│   │   │   ├── login_action.py       # ol_ensure_login
│   │   │   ├── search_page.py        # ol_collect_books
│   │   │   ├── detail_page.py        # ol_add_to_shelf
│   │   │   └── reading_list_action.py  # ol_clear_reading_list, ol_store_count,
│   │   │                               #   ol_assert_count, ol_ensure_count
│   │   └── workflows/                # JSON orchestration — zero selectors
│   │       ├── ol_search_and_add.json
│   │       ├── ol_add_only.json
│   │       ├── ol_ensure_count.json
│   │       ├── ol_regression_roundtrip.json
│   │       ├── ol_multi_author.json
│   │       ├── ol_parallel_perf.json
│   │       ├── ol_smoke_test.json
│   │       ├── ol_idempotency_test.json
│   │       └── login.json
│   │
│   └── sites/saucedemo/
│       ├── pages/                    # Glue layer
│       │   ├── login_action.py       # sd_login
│       │   ├── inventory_action.py   # sd_add_to_cart, sd_sort_products
│       │   ├── cart_action.py        # sd_view_cart
│       │   └── checkout_action.py    # sd_checkout
│       └── workflows/
│           ├── sd_happy_path.json
│           ├── sd_multi_product.json
│           └── sd_smoke_test.json
│
└── requirements.txt
```

---

# Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENLIBRARY_USERNAME` | — | Login email (required) |
| `OPENLIBRARY_PASSWORD` | — | Login password (required) |
| `OPENLIBRARY_HEADLESS` | `true` | `false` to watch the browser |
| `OPENLIBRARY_SLOW_MO_MS` | `0` | Slow down actions (ms) for debugging |
| `OPENLIBRARY_BROWSER` | `chromium` | `firefox` or `webkit` also supported |
| `OPENLIBRARY_BASE_URL` | `https://openlibrary.org` | Override for local/staging |
| `GROQ_API_KEY` | — | AI resolver fallback (free tier) |
| `GEMINI_API_KEY` | — | AI resolver fallback |
| `ANTHROPIC_API_KEY` | — | AI resolver last resort |

---

# Summary

This project demonstrates two complementary approaches to automation:

1. **Exam layer** (`exam/`) — clean POM + pytest, exam-compliant, data-driven via `testdata.json`
2. **Stepper Framework** (`stepper/`) — JSON-driven orchestration engine with smart locators,
   retry, conditional flows, parallel execution, and multi-site support

Both layers share the same `poms/` classes. Neither duplicates the other — they are complementary,
not redundant.
