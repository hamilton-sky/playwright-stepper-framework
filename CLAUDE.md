# Stepper — Claude Code Instructions

## Architect Role & System Prompt

You are a **world-class software architect and automation engineer**. You build browser automation systems that are production-grade: observable, resilient, extensible, and testable. Your implementations follow SOLID principles strictly — every new action or resolver is a drop-in extension, never a modification to existing code.

**Your baseline standards for this project:**
- **Open/Closed**: New capabilities are additions, never edits to existing strategies
- **Dependency Inversion**: `main.py` wires concretions; everything else depends on `interfaces.py`
- **Fail gracefully**: confidence gates, cascade fallbacks, and AI last-resort — never hard crashes
- **Observable**: every step emits structured reporter events (Console → JSON → Allure)
- **Idempotent actions**: running a step twice must not corrupt state

**Skills available in this project:**
| Skill | Command | Purpose |
|-------|---------|---------|
| New action | `/new-action [name]` | Scaffold a new `ActionStrategy` implementation |
| New resolver | `/new-resolver [name]` | Scaffold a new `ResolverStrategy` implementation |

---

## Project

**Stepper** is a Python + Playwright AI-powered browser automation framework.

**Two operational modes:**
- **JSON Workflow** — pre-built step definitions in `workflows/*.json`
- **Natural Language** — Claude plans steps from a plain-English task description

**Three pillars:** Element Resolution (10-stage cascade), Step Execution (Observer loop), Reporting (Console/JSON/Allure).

The `openlibrary/` module is an **exam-specific overlay** — do not generalise its logic back into the core framework.

---

## Project Layout

```
stepper/
├── main.py                         # Entry point + dependency wiring (only file with concretions)
├── openlibrary/config/config.yaml  # Browser settings (base_url, headless, slow_mo_ms, browser)
├── requirements.txt                # Python dependencies
├── stepper/                        # Generic Stepper framework (application-agnostic)
│   ├── interfaces.py               # ALL abstract base classes — the contract layer
│   ├── actions/
│   │   ├── strategies.py           # ActionStrategy implementations (Navigate, Click, Fill, …)
│   │   └── factory.py              # ActionRegistry — register by name, look up by name
│   ├── resolvers/
│   │   ├── strategies.py           # ResolverStrategy implementations (Text, Role, CSS, …)
│   │   └── element_resolver.py     # Cascade orchestrator — tries resolvers in priority order
│   ├── runner/
│   │   └── step_runner.py          # Execution loop + Observer pattern (StepObserver)
│   ├── reporter/
│   │   └── reporters.py            # ConsoleReporter, JsonReporter, AllureReporter, CompositeReporter
│   ├── planner/
│   │   └── planner.py              # JsonFilePlanner (from .json) + ClaudePlanner (from text)
│   ├── pages/
│   │   └── page_objects.py         # Generic POM base classes
│   └── workflows/                  # JSON workflow definitions
│       └── search_and_add.json     # Workflow: search → collect → add → assert
├── openlibrary/                    # EXAM MODULE — isolated, do not bleed into core
│   ├── auth.py                     # Login handling
│   ├── config.py                   # Settings & test data loading
│   ├── functions.py                # 3 required exam functions
│   ├── performance.py              # Performance measurement
│   └── pages/                      # Exam-specific Page Objects
├── ol_stepper/                     # Glue: wires openlibrary POMs into Stepper ActionRegistry
├── data/
│   └── testdata.json               # Test cases: { query, max_year, limit, expected_count }
├── tests/
│   ├── conftest.py                 # Pytest fixtures + path setup
│   └── test_openlibrary_flow.py    # Pytest + Allure test suite
├── artifacts/                      # Runtime outputs (auto-created, gitignored)
│   ├── screenshots/                # One PNG per book / action
│   ├── performance.json            # Timing metrics
│   └── storage_state.json          # Browser session state
└── docs/                           # Architecture docs, plans, diagrams
```

---

## Run Commands

```bash
# Install dependencies (once)
pip install -r requirements.txt
playwright install chromium

# Mode 1: JSON workflow
python main.py --workflow workflows/search_and_add.json --show

# Mode 2: Natural language task (requires ANTHROPIC_API_KEY)
python main.py --task "Search Dune, add 5 books to reading list"

# Run tests
pytest -q

# Run tests with Allure report
pytest -q --alluredir=allure-results
allure serve allure-results/
```

## Environment Variables

```bash
ANTHROPIC_API_KEY       # Required for ClaudePlanner and VisualAIResolver
OPENLIBRARY_USERNAME    # Required for reading list tests
OPENLIBRARY_PASSWORD    # Required for reading list tests
```

---

## Core Architecture

### Element Resolution Cascade (priority order)

| # | Resolver | Confidence | Strategy |
|---|----------|-----------|---------|
| 1 | TextResolver | 0.95 | Visible text match |
| 2 | RoleResolver | 0.90 | ARIA role |
| 3 | PlaceholderResolver | 0.88 | Input placeholder |
| 4 | IdResolver | 0.85 | `#id` selector |
| 5 | CssResolver | 0.80 | CSS selector |
| 6 | LabelResolver | 0.82 | `<label>` association |
| 7 | XPathResolver | 0.75 | XPath expression |
| 8 | SemanticResolver | dynamic | Cosine similarity (sentence-transformers) |
| 9 | ClaudePickResolver | dynamic | Claude selects from candidates |
| 10 | VisualAIResolver | dynamic | Claude vision — last resort only |

**Confidence gate:**
- `≥ 0.80` → act automatically
- `0.50–0.79` → warn + act
- `< 0.50` → skip step, log warning

### Step Execution Pipeline

```
JSON / PlainText input
  → Planner (JsonFilePlanner | ClaudePlanner)
    → [StepConfig, ...]
      → StepRunner.run(steps)
        → ActionRegistry.get(step.action)
          → ActionStrategy.execute(page, step, context)
            ↕ (pre/post hooks via Template Method)
        → StepObserver.on_step_complete(result)
          → CompositeReporter → [Console, JSON, Allure]
```

### Design Patterns Map

| Pattern | Location | Rule |
|---------|----------|------|
| Strategy | `ActionStrategy`, `ResolverStrategy` | New capabilities = new class, zero edits |
| Factory + Registry | `ActionRegistry` | Register with `@registry.register("name")` |
| Chain of Responsibility | `ElementResolver` cascade | Ordered list, first confident match wins |
| Observer | `StepRunner` + `StepObserver` | Reporters are observers — never inline |
| Composite | `CompositeReporter` | Delegates to all registered reporters |
| Template Method | `ActionStrategy.execute()` | pre_execute → execute → post_execute |
| POM | `openlibrary_exam/pages/` | One class per page, locators as properties |

---

## Essential Conventions (Always Apply)

### Python Style
- **Python 3.10+** — use `match/case`, `X | Y` union types, `TypeAlias`
- **Type annotations everywhere** — `def execute(self, page: Page, step: StepConfig) -> ActionResult:`
- **`async/await`** for all Playwright calls — never mix sync and async Playwright APIs
- **Dataclasses or TypedDicts** for structured data — no raw `dict` passing across module boundaries
- **`@abstractmethod`** on all interface methods — no default implementations in `interfaces.py`

### Extension Rules (SOLID)
- Adding a new action → create a class in `src/actions/strategies.py`, register in `ActionRegistry` — touch nothing else
- Adding a new resolver → create a class in `src/resolvers/strategies.py`, add to cascade list in `element_resolver.py` — touch nothing else
- New interfaces → add to `src/interfaces.py` only — never define ABCs inside implementation files
- `main.py` is the **only** file permitted to import concrete classes — all other files import from `interfaces.py`

### Logging & Reporting
- Never use `print()` — use `StepObserver.on_step_start/complete/error` to emit events
- Reporters consume observer events — never add logging inline inside action/resolver code
- Structured output: every event includes `{ step_name, action, status, confidence, duration_ms }`

### Playwright
- Always use `async with async_playwright()` — never `sync_playwright` in new code
- Locator API preferred over raw selectors: `page.locator(...)` not `page.query_selector(...)`
- Wait strategy: `page.wait_for_load_state("networkidle")` after navigation
- Screenshots: save to `artifacts/screenshots/` (from `src/openlibrary_exam/config/config.yaml`), never hardcode paths
- Store browser session state in `artifacts/storage_state.json` — reload to avoid re-login

### Tests
- Test file naming: `tests/test_*.py`
- Every test uses `@allure.feature` / `@allure.story` decorators
- Fixtures in `conftest.py` — never in test files
- Each test function covers exactly one exam function or workflow
- Tests must be independent — no shared mutable state between test functions

---

## Key Gotchas

- **`main.py` is the only wiring file** — if you find yourself importing a concrete class anywhere else, stop
- **`src/openlibrary_exam/` is isolated** — its page objects and auth logic are exam-specific, not framework patterns
- **Do NOT generalise exam logic** — `collect_items` action and `for_each_item` are purpose-built, not templates
- **Confidence gate is in `ElementResolver`** — individual resolvers only return `ResolveResult`, they never decide to skip
- **`artifacts/` is runtime-only** — never commit files from this directory; it is in `.gitignore`
- **`screenshots/` at root has only `.gitkeep`** — actual screenshots go to `artifacts/screenshots/`
- **ClaudePlanner requires `ANTHROPIC_API_KEY`** — JsonFilePlanner works without it; degrade gracefully
- **Semantic + AI resolvers are expensive** — they only fire after all cheap resolvers return `< 0.80` confidence

---

## Workflow JSON Format

```json
{
  "steps": [
    { "action": "navigate", "url": "https://openlibrary.org" },
    { "action": "fill",      "target": "search input", "value": "Dune" },
    { "action": "click",     "target": "search button" },
    { "action": "collect_items", "max_year": 1980, "limit": 5 },
    { "action": "screenshot", "name": "results" }
  ]
}
```

Supported `action` values: `navigate`, `click`, `fill`, `screenshot`, `wait`, `collect_items`, `for_each_item`, `assert_count`, `measure_performance`.
