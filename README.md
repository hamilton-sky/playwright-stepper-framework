# OpenLibrary Automation — Stepper Framework

End-to-end automation suite for [openlibrary.org](https://openlibrary.org) built with Playwright + Python.
Demonstrates **POM**, **OOP**, **SOLID**, **Data-Driven** design, and **Smart Locators** as required by the exam spec.

> **Examiner**: see [SUBMISSION.md](SUBMISSION.md) for the two run options, a SOLID walkthrough with file references, and an architectural patterns guide.

---

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

> **Rule:** JSON contains *action names and parameters only — never CSS selectors or XPaths.*
> All element knowledge lives exclusively in the POM `Locators` inner classes.

---

## Project Structure

```
playwright-stepper-framework/
│
├── poms/                           # Pure Page Object Model layer
│   ├── shared/                     # Shared across ALL sites
│   │   ├── interfaces.py           # IBrowserDriver, IElementHandle, Delays (DIP contracts)
│   │   ├── driver.py               # PlaywrightDriver — implements IBrowserDriver
│   │   ├── base_page.py            # SharedBasePage — resolver helpers
│   │   └── performance.py          # measure_page_performance() — raw timing via JS API
│   ├── openLibrary/                # OpenLibrary POMs
│   │   ├── config.py               # 3-tier settings: defaults → config.yaml → ENV
│   │   ├── pages/
│   │   │   ├── base_page.py        # BasePage: open(), navigate(), delay helpers
│   │   │   ├── login_page.py       # LoginPage: selectors + is_session_live()
│   │   │   ├── book_search_page.py # search(), collect_books_under_year() + pagination
│   │   │   ├── book_detail_page.py # add_to_reading_list(), remove_from_shelf()
│   │   │   └── reading_list_page.py  # get_book_count(), collect_all_book_urls()
│   │   ├── utils/
│   │   │   ├── book_filter.py      # extract_year_from_text(), is_under_year() — pure functions
│   │   │   ├── shelf.py            # SHELF_LABEL_WANT / SHELF_LABEL_ALREADY constants
│   │   │   └── screenshot.py       # ScreenshotManager helper
│   │   └── data/
│   │       └── testdata.json       # Parametrised test cases (query, max_year, limit)
│   ├── saucedemo/                  # SauceDemo POMs
│   └── phpTravels/                 # phpTravels POMs
│
├── exam/                           # Pytest exam suite — calls poms/ directly
│   ├── flows.py                    # 4 exam function signatures (orchestration layer)
│   │                               #   search_books_by_title_under_year(page, query, max_year, limit)
│   │                               #   add_books_to_reading_list(page, urls)
│   │                               #   assert_reading_list_count(page, expected_count)
│   │                               #   measure_page_performance(page, url, threshold_ms)
│   ├── conftest.py                 # Fixtures: browser (session), page (function),
│   │                               #   auth via storage_state.json, --headed / --case flags
│   ├── pytest.ini                  # asyncio_mode = auto
│   ├── ReadMeAIBugs.md             # Static analysis: 5 bugs found in the exam starter script
│   └── tests/
│       └── test_openlibrary_exam.py  # TestOpenLibraryExam: search → add → assert → perf
│
├── stepper/                        # Stepper framework + site integrations
│   ├── main.py                     # DIP root — wires registry, resolver, runner, reporter
│   ├── pytest.ini                  # asyncio_mode = auto, alluredir, log_cli settings
│   ├── engine/                     # Core engine (site-agnostic)
│   │   ├── interfaces.py           # StepConfig, StepResult, ExecutionContext,
│   │   │                           #   ActionStrategy, ResolverStrategy (all abstract)
│   │   ├── utils.py                # dict_to_step_config() — single source of truth
│   │   ├── actions/
│   │   │   ├── factory.py          # ActionRegistry + build_default_registry()
│   │   │   └── strategies.py       # navigate, click, fill, hover, select, screenshot,
│   │   │                           #   wait, store_count, assert_count, for_each_item,
│   │   │                           #   extract_data, paginate, ensure_login,
│   │   │                           #   measure_performance, run_workflow, parallel
│   │   ├── resolvers/
│   │   │   ├── element_resolver.py # Cascade executor + DefaultResolverFactory
│   │   │   └── strategies.py       # Role → Label → Placeholder → Text → Id →
│   │   │                           #   Css → XPath → Semantic → VisualAI
│   │   ├── runner/
│   │   │   ├── step_runner.py      # Execution loop, retry, observer notifications
│   │   │   ├── api.py              # StepperSession + run_steps() public API
│   │   │   └── when_eval.py        # Condition evaluator: context_equals, url_contains,
│   │   │                           #   element_exists, context_key_exists, not/all/any
│   │   ├── reporter/
│   │   │   ├── reporters.py        # CompositeReporter, ConsoleReporter, JsonReporter,
│   │   │   │                       #   AllureReporter, TestReportReporter
│   │   │   ├── test_report_manager.py   # Run directory + metadata management
│   │   │   └── test_report_reporter.py  # Per-run file reporter implementation
│   │   ├── planner/
│   │   │   └── planner.py          # JsonFilePlanner (loads JSON) + ClaudePlanner (AI)
│   │   └── pages/
│   │       └── base_page_module.py # PageModule base — enforces ol_ action_name prefix
│   │
│   ├── sites/openlibrary/          # OpenLibrary integration (site module pattern)
│   │   ├── pages/                  # Stepper ↔ poms/ glue (thin adapters)
│   │   │   ├── login_action.py     # ol_ensure_login
│   │   │   ├── search_page.py      # ol_collect_books
│   │   │   ├── detail_page.py      # ol_add_to_shelf
│   │   │   └── reading_list_action.py  # ol_clear_reading_list, ol_store_count,
│   │   │                               #   ol_assert_count, ol_ensure_count
│   │   └── workflows/              # JSON orchestration — zero selectors
│   │       ├── ol_search_and_add.json      # Main flow: clear → search → add → assert
│   │       ├── ol_add_only.json            # Append-only (idempotent)
│   │       ├── ol_ensure_count.json        # Top-up to target N
│   │       ├── ol_regression_roundtrip.json  # Full lifecycle + delta/absolute asserts
│   │       ├── ol_multi_author.json          # Two-query sequential composition
│   │       ├── ol_parallel_perf.json         # 3-page concurrent benchmark (parallel tabs)
│   │       ├── ol_smoke_test.json            # when-guarded non-mutating health check
│   │       ├── ol_idempotency_test.json      # Add twice → count stays same
│   │       └── login.json                    # Generic login subflow (reusable)
│   │
│   ├── tests/                      # Stepper engine test suite
│   │   ├── conftest.py             # --headed flag registration
│   │   └── test_workflow.py        # Workflow integration tests
│   │
│   ├── models/
│   │   └── all-MiniLM-L6-v2/      # Pre-trained sentence embeddings (semantic resolver)
│   ├── artifacts/                  # Runtime cache (storage_state.json, screenshots)
│   └── reports/                    # Output: allure-results/, per-run folders
│
└── requirements.txt                # All dependencies (install from repo root)
```

---

## Exam Function Signatures

The four required functions live in `exam/flows.py` and delegate to `poms/` POM classes:

```python
# exam/flows.py
async def search_books_by_title_under_year(
    page, query: str, max_year: int, limit: int = 5
) -> list[str]:
    """Search OpenLibrary, filter by publication year, paginate until limit reached."""
    driver = PlaywrightDriver(page)
    search_page = BookSearchPage(driver, settings.base_url, settings.delays)
    await search_page.search(query)
    return await search_page.collect_books_under_year(max_year, limit)


async def add_books_to_reading_list(page, urls: list[str]) -> None:
    """Open each book URL and add to Want to Read / Already Read (random) + screenshot."""
    driver = PlaywrightDriver(page)
    for idx, url in enumerate(urls, start=1):
        detail = BookDetailPage(driver, settings.base_url, book_url=url, delays=settings.delays)
        await detail.open()
        await detail.add_to_reading_list()          # random shelf label per exam spec
        await screenshot_mgr.capture(f"book_{idx}_{slug}")


async def assert_reading_list_count(page, expected_count: int) -> None:
    """Navigate to both shelves, count books, assert against expected."""
    driver = PlaywrightDriver(page)
    reading_list = ReadingListPage(driver, settings.base_url, settings.delays)
    actual = await reading_list.get_book_count()
    assert actual == expected_count, f"Expected {expected_count} books, got {actual}"


async def measure_page_performance(page, url: str, threshold_ms: int) -> dict:
    """Measure first_paint_ms, dom_content_loaded_ms, load_time_ms. Writes performance_report.json."""
    driver = PlaywrightDriver(page)
    return await _measure_perf(driver, url, threshold_ms, output_path=settings.performance_output)
```

---

## Smart Locators — Resolver Cascade

The `ElementResolver` tries strategies in resilience order, stopping at the first confident match:

| Priority | Strategy | Confidence | Why |
|---|---|---|---|
| 1 | `role` + `name` | 0.95 | ARIA — survives CSS renames |
| 2 | `label` text | 0.93 | Tied to UX copy, very stable |
| 3 | `placeholder` | 0.90 | Input-specific, stable |
| 4 | visible `text` | 0.85 | Good for buttons/links |
| 5 | element `id` | 0.82 | Stable but sometimes generated |
| 6 | `css` selector | 0.75 | Fragile — last deterministic resort |
| 7 | `xpath` | 0.70 | Most brittle |
| 8 | Semantic AI | — | Groq → Gemini → Claude fallback chain |

If a step is ambiguous (multiple matches), the engine applies semantic scoring against the step's `description` before falling back to AI disambiguation.

---

## Showcase Workflows

Nine ready-to-run JSON workflows demonstrating every architectural capability:

| Workflow | What it showcases | Command (run from `stepper/`) |
|---|---|---|
| `ol_search_and_add.json` | Main exam flow: clear → search → add → assert | `python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json` |
| `ol_add_only.json` | Idempotent append (no clear) | `python main.py --workflow sites/openlibrary/workflows/ol_add_only.json` |
| `ol_ensure_count.json` | Top-up: add only the gap needed to reach N | `python main.py --workflow sites/openlibrary/workflows/ol_ensure_count.json` |
| `ol_regression_roundtrip.json` | Full lifecycle + two assert modes (delta & absolute 0) | `python main.py --workflow sites/openlibrary/workflows/ol_regression_roundtrip.json` |
| `ol_multi_author.json` | Two-query sequential composition (Dune + Tolkien) | `python main.py --workflow sites/openlibrary/workflows/ol_multi_author.json` |
| `ol_parallel_perf.json` | Three pages benchmarked concurrently in separate tabs | `python main.py --workflow sites/openlibrary/workflows/ol_parallel_perf.json` |
| `ol_smoke_test.json` | `when`-guarded + `continue_on_failure` flow-level soft-fail | `python main.py --workflow sites/openlibrary/workflows/ol_smoke_test.json` |
| `ol_idempotency_test.json` | Add same books twice → count must not grow | `python main.py --workflow sites/openlibrary/workflows/ol_idempotency_test.json` |
| `login.json` | Generic reusable login subflow | `python main.py --workflow sites/openlibrary/workflows/login.json` |

## Step Controls

Every step supports these optional fields — resolved at plan time, no runner changes needed:

| Field | Default | Effect |
|---|---|---|
| `when` | — | Skip step if condition is false — see full condition reference below |
| `retry` | `0` | Retry on failure up to N times |
| `retry_delay_ms` | `1000` | Milliseconds between retries |
| `continue_on_failure` | `false` | `true` → warn and continue; `false` → hard-stop |

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

### Runtime variable resolution

`variables{}` in the JSON are substituted at **plan time** by `JsonFilePlanner`.  
Context values set by earlier steps are substituted at **runtime** by `StepRunner` — this means `{{gap}}` in a step's `extra` resolves to the integer stored by `ol_ensure_count` at the moment the step runs:

```json
{ "action": "ol_collect_books",
  "when": { "context_greater_than": { "key": "gap", "value": 0 } },
  "extra": { "limit": "{{gap}}" }
}
```

A pure `"{{key}}"` reference preserves the original type (int, bool). Mixed strings like `"page_{{n}}"` are string-substituted.

---

### Flow-level defaults (declared once at the top, inherited by all steps):

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

Override any variable at runtime without touching the JSON:

```bash
cd stepper

# Change query and limit for any workflow
python main.py --workflow sites/openlibrary/workflows/ol_regression_roundtrip.json \
  --vars '{"query":"Asimov","max_year":1960,"limit":2}'

# Run in headed mode to watch the browser
python main.py --workflow sites/openlibrary/workflows/ol_parallel_perf.json --show
```

---

## Exam Suite (`exam/`)

A standalone pytest suite that exercises the four required exam functions directly, without the Stepper engine.

```
exam/
├── flows.py          ← 4 exam functions (orchestration layer)
│                          search_books_by_title_under_year(page, query, max_year, limit)
│                          add_books_to_reading_list(page, urls)
│                          assert_reading_list_count(page, expected_count)
│                          measure_page_performance(page, url, threshold_ms)
├── conftest.py       ← Fixtures: browser (session), page (function, pre-authed),
│                          storage_state.json cache, --headed / --case / --all-cases flags
├── pytest.ini        ← asyncio_mode = auto
└── tests/
    └── test_openlibrary_exam.py
           TestOpenLibraryExam
             test_search_books           → assert URLs returned, shape correct
             test_add_books              → add to shelf, capture count_before/after
             test_assert_reading_list_count → delta check + live count assertion
             test_measure_performance_search   → assert metrics dict present
             test_measure_performance_detail   → assert load_time_ms key
             test_measure_performance_reading_list → reading list page benchmark
```

**Authentication**: on first run the suite logs in and saves `artifacts/storage_state.json`. Every subsequent run loads the saved cookies — no re-login.

```bash
cd exam

# Run all tests (default test case from testdata.json)
pytest tests/ -v

# Run headed so you can watch
pytest tests/ -v --headed

# Run a specific test case by index
pytest tests/ -v --case 1

# Run all parametrised test cases
pytest tests/ -v --all-cases

# Generate Allure report
pytest tests/ -v --alluredir=reports/allure-results
allure serve reports/allure-results
```

**Difference vs Stepper workflows**: `exam/` calls `flows.py` functions directly (Python-level). The Stepper workflows call `ol_*` action names through the registry (JSON-level). Both hit the same `poms/` layer — they are complementary, not redundant.

---

## Quick Start

### 1. Install dependencies

```bash
# from the repo root
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in:
# OPENLIBRARY_USERNAME=your@email.com
# OPENLIBRARY_PASSWORD=yourpassword
```

### 3. Run the exam flow

**Option A — JSON workflow (Stepper engine):**
```bash
cd stepper
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json
```

**Option B — pytest (exam suite):**
```bash
cd exam
pytest tests/ -v
```

**Option C — headed browser (for debugging):**
```bash
python main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json --show
```

---

## Data-Driven Configuration

Workflow variables are declared once and substituted throughout the flow:

```json
{
  "variables": {
    "query":    "Dune",
    "max_year": 1980,
    "limit":    5
  },
  "steps": [
    { "action": "ol_collect_books",
      "extra": { "query": "{{query}}", "filter": { "year_max": "{{max_year}}" }, "limit": "{{limit}}" }
    }
  ]
}
```

Override at runtime without touching JSON:
```bash
python main.py --workflow ol_search_and_add.json --vars '{"query":"Tolkien","limit":3}'
```

ENV variables override `config.yaml` which overrides defaults — full 3-tier config hierarchy.

---

## Available Stepper Actions

| Action | Description |
|---|---|
| `ol_ensure_login` | `LoginPage.is_session_live()` → fill + submit if needed |
| `ol_collect_books` | Search + filter by year + paginate → fills `context.collected_items`; `limit` from `extra` (supports `"{{gap}}"` runtime resolution) |
| `ol_add_to_shelf` | Add each collected book to a reading shelf + screenshot |
| `ol_clear_reading_list` | Remove all books from want-to-read shelf |
| `ol_store_count` | Count books across both shelves → stores in `context` |
| `ol_assert_count` | Assert count equals `expected_count` or `count_before + delta` |
| `ol_ensure_count` | Count shelf, store `gap` in context if top-up needed — flow controls collect/add/assert via `when` guards |
| `navigate` | Go to URL |
| `click` | Click element (with Smart Locator cascade) |
| `fill` | Type into input + press Enter |
| `hover` | Hover over element (triggers CSS :hover menus) |
| `select` | Select from `<select>` dropdown by label, index, or value |
| `screenshot` | Capture screenshot to file |
| `wait` | Wait for selector, URL fragment, or fixed seconds |
| `extract_data` | Scrape DOM data into `context.extracted_data` |
| `for_each_item` | Loop over `context.collected_items`, run sub-steps per item |
| `store_count` | Count elements via CSS selectors, store in `context` |
| `assert_count` | Assert element count matches expected (CSS or context source) |
| `measure_performance` | Collect `first_paint_ms`, `dom_content_loaded_ms`, `load_time_ms` |
| `ensure_login` | Generic login subflow — accepts `login_steps` list in config |
| `run_workflow` | Execute a sub-workflow JSON file then return to parent flow |
| `parallel` | Run multiple `read_only` sub-steps concurrently in separate tabs |

---

## Reports & Artifacts

| Artifact | Location | Generated by |
|---|---|---|
| Allure report | `reports/allure-results/` | `AllureReporter` |
| JSON report | `report.json` | `JsonReporter` |
| Test run folder | `reports/<timestamp>_<name>/` | `TestReportReporter` |
| Screenshots | `reports/<run>/screenshots/` | Auto after each step |
| Run log | `reports/<run>/logs/run.log` | File log handler |
| Performance data | `artifacts/performance.json` | `measure_performance` action |

**Open Allure report:**
```bash
allure serve reports/allure-results
```

---

## Design Principles

| Principle | Implementation |
|---|---|
| **SRP** | Each class has one job: `StepRunner` runs steps, `ElementResolver` finds elements, `BookSearchPage` knows the search page |
| **OCP** | Add a new site: create a folder + register. Add a new action: subclass `ActionStrategy` + register. Zero edits to existing code |
| **DIP** | `StepRunner` depends on `ActionFactory` interface, never on `OLCollectBooksAction` directly |
| **POM** | All selectors live in `Locators` inner classes. JSON and glue layers never duplicate selector strings |
| **Data-Driven** | Workflow logic is JSON; parameters are variables; env overrides config; test data separates from code |

---

## Environment Variables

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
