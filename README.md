# Stepper Framework

A JSON-driven automation engine in Python, built on Playwright but no longer bound to it.

Workflows are declarative: a JSON file names *what* to do, the engine decides *how* to run
it — retries, conditional branching, context passing, parallelism and reporting — and a
three-layer architecture keeps every CSS selector in the page-object layer, out of both the
engine and the JSON.

Each action declares the **domain** it acts on, and the engine hands it that domain's
session. For the three browser sites that is a Playwright `Page`; for the `db` domain it is
a `sqlite3.Connection`. One workflow can use both: a step can read a value off a rendered
page and a later step can assert it through SQL, sharing one context and one report.

When a selector breaks, the resolver cascade and the self-healing pipeline try to find the
element anyway, escalating from free local strategies to paid AI only when they have to.

```mermaid
flowchart LR
    A["<b>JSON Workflow</b><br/>WHAT to do"] --> B["<b>Stepper Engine</b><br/>HOW to run it"]
    B --> C["<b>POM Layer</b><br/>WHERE elements are"]
    C --> D["<b>Playwright</b><br/>DO it"]

    style A fill:#e8f0fe,stroke:#4285f4,color:#111
    style B fill:#e6f4ea,stroke:#34a853,color:#111
    style C fill:#fef7e0,stroke:#fbbc04,color:#111
    style D fill:#f1f3f4,stroke:#9aa0a6,color:#111
```

---

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt
playwright install chromium

#    Optional: pre-cache the ML models used by the semantic resolver and the
#    healer. Both fall back to downloading on first use, so this is only needed
#    to warm the cache ahead of time or to run offline.
python stepper/download_models.py

# 2. Configure — .env belongs at the repo root, where both the engine and
#    the examples look for it first
cp stepper/.env.example .env
#    Fill in OPENLIBRARY_USERNAME / OPENLIBRARY_PASSWORD, plus at least one of
#    GROQ_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY if you want AI resolution.

# 3. Verify the install — no browser, no network, no credentials
pytest stepper/tests/unit/

# 4. See what there is to run
python stepper/main.py list

# 5. Run a workflow — by name, not by path
python stepper/main.py run sd_happy_path
```

The three sites here are demos. To drive your own app, see
**[docs/adding-your-app.md](docs/adding-your-app.md)** — six files, no edits to
anything that already exists.

### Commands

| Command | What it does |
|---|---|
| `run WORKFLOW` | Run a workflow, or `--task` to plan one from natural language |
| `list` | Every workflow on disk, grouped by site, with step counts |
| `actions` | Every registered action and what it does |
| `validate` | Check workflows without launching a browser — exits 1 if any is invalid |
| `heal apply WORKFLOW` | Review and apply the healer's selector fixes |

`python stepper/main.py <command> --help` explains one command's options.

Useful `run` flags: `--show` (headed browser), `--video`, `--allure-serve`, `--ci`,
`--vars '{"query":"Dune"}'`, `--data <testdata.json>`, `--heal N`,
`--no-heal-cache` (resolve every heal through the cascade instead of replaying
`heal_cache.json` — what you want when measuring what the healer can actually do).

Workflows are referred to by name — `sd_happy_path` resolves across all sites, and
full paths still work anywhere a name is accepted. The older flag-only form
(`--workflow <path>`) also still works, with a one-line note pointing at the new
spelling.

---

## Three-Layer Architecture

```
  Layer         Location                      Responsibility
  ────────────  ────────────────────────────  ──────────────────────────────────────────
  Flow (JSON)   stepper/sites/*/workflows/    Order, conditions, variables.
                                              No selectors. No imperative logic.

  Glue          stepper/sites/*/pages/        Wraps a POM into a named Stepper action.
                                              One action, one job.
                                              Injects page=, resolver=, behaviour=.

  POM           poms/*/pages/                 Selectors + raw page interactions only.
                                              No flow logic. No credentials.
                                              Interactive locators are Locator objects.
```

**Dependency direction is one-way: Flow → Glue → POM. Never reversed.**

Every element identifier lives in a `Locator` value object inside a POM's `Locators` inner
class. Workflow JSON contains action names and parameters only — never a CSS selector.

### The fourth axis: domains

The three layers say *where* code lives. A **domain** says *what a step acts on*.

```
  ┌────────────────────────────────────────────────────────────┐
  │  StepRunner — steps, results, retry, healing, observers    │
  │  knows nothing about browsers, pages or selectors          │
  └──────────────────────────┬─────────────────────────────────┘
                             │ per step: which domain?
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   ┌─────────┐         ┌───────────┐        ┌──────────┐
   │   web   │         │    db     │        │   noop   │
   │  Page   │         │Connection │        │  object  │
   └─────────┘         └───────────┘        └──────────┘
```

A domain supplies its own session, hooks, `when` vocabulary and preflight check, and
declares itself from its own folder under `stepper/sites/` — no central file lists them.
Sessions open on first use and close in reverse order, so a db-only workflow never launches
a browser.

The POM layer stays browser-only. A non-browser domain has no selectors, so it has no POMs
and its actions subclass `ActionStrategy` directly rather than `GlueAction`.

Full diagrams: [ARCHITECTURE.md](ARCHITECTURE.md).
Where things stand: [docs/state-of-the-stepper.md](docs/state-of-the-stepper.md).
Layer rules: [.claude/rules/three-layer-contract.md](.claude/rules/three-layer-contract.md).

---

## Smart Locators — Resolver Cascade

`ElementResolver` tries strategies in resilience order and stops at the first confident
match, escalating only when cheaper phases are ambiguous:

```mermaid
flowchart TD
    CFG["Locator.to_cfg()"] --> P1["<b>Phase 1 — deterministic</b> · free<br/>role → label → placeholder → text → id → css → xpath"]
    P1 --> Q1{"exactly 1 match?"}
    Q1 -->|yes| ACT["act"]
    Q1 -->|"0 or 2+"| P2["<b>Phase 2 — semantic</b> · local, ~30ms<br/>MiniLM-L6-v2 cosine similarity"]
    P2 --> Q2{"score ≥ 0.80<br/>and unique?"}
    Q2 -->|yes| ACT
    Q2 -->|no| P3["<b>Phase 3 — AI pick</b> · paid<br/>Groq → Gemini → Claude"]
    P3 --> Q3{"confidence ≥ 0.70?"}
    Q3 -->|yes| ACT
    Q3 -->|no| FB["fall back to top semantic result"]

    style P1 fill:#e6f4ea,stroke:#34a853,color:#111
    style P2 fill:#fef7e0,stroke:#fbbc04,color:#111
    style P3 fill:#fce8e6,stroke:#ea4335,color:#111
    style ACT fill:#e8f0fe,stroke:#4285f4,color:#111
```

Priority order mirrors Playwright's own locator guidance: `role` survives redesigns,
`xpath` encodes the whole DOM shape and breaks first. Details and the confidence
constants: [.claude/rules/resolver-cascade.md](.claude/rules/resolver-cascade.md).

The cascade is optional. A POM built with `resolver=None` falls back to its `Locator`'s
CSS candidates and works with no AI, no keys and no network — see
[`examples/plain_pom/`](examples/plain_pom/).

---

## Self-Healing — DOM Snapshot Cascade

When a step fails, `DOMSnapshotCascade` scores every interactive element on the page
before spending a single AI token:

```mermaid
flowchart TD
    E["all ~50 interactive elements"] --> B1["Phase 1 — MiniLM bi-encoder · ~30ms<br/>score every element independently"]
    B1 --> T5["top 5 candidates"]
    T5 --> B2["Phase 2 — cross-encoder re-rank · ~50ms<br/>reads (query | element) as one string"]
    B2 --> D{"score"}
    D -->|"≥ 0.85, unique"| Z["healed cfg ready<br/><b>0 AI tokens</b>"]
    D -->|"≥ 0.85, ambiguous"| A1["~30 tokens"]
    D -->|"0.50 – 0.85"| A2["scoped DOM · ~100 tokens"]
    D -->|"< 0.50"| A3["full ARIA snapshot · ~400 tokens"]

    style Z fill:#e6f4ea,stroke:#34a853,color:#111
    style A3 fill:#fce8e6,stroke:#ea4335,color:#111
```

**The top rung needs no API key.** A unique match above 0.85 is healed from the
element's own attributes — no provider is called, so `--heal` is useful on a stock
install with an empty `.env`. Keys buy the lower rungs, not the feature. Without
them the AI rungs fail per-step and the run reports those heals as failed;
anything the embeddings resolve is still healed for nothing.

Opt a step out with `"heal": false`. Verify a heal landed with `"heal_assert"` —
and note that `heal_assert` is checked on the cached path as well as the cascade,
so a stale `heal_cache.json` entry cannot report a heal it did not achieve.

Apply cached heal suggestions back into the workflow JSON after a run:

```bash
python stepper/main.py heal apply sd_full_heal_flow
```

It finds the most recent `heal_suggestions.json` under `reports/`, shows a per-step
before/after diff, and patches the JSON in place (`--yes` to skip confirmation).

`sd_heal_test.json` and `sd_full_heal_flow.json` ship with deliberately broken selectors.
Run them with `--heal 2 --no-heal-cache` to watch the cascade recover each one — the
embed-direct rung needs no API key.

They are **not** yet part of CI, and the honest reason is worth knowing: an
`assert_*` step resolves through the full cascade, fuzzy fallbacks included, so an
assertion can pass by matching a *different* element than the one it names. Until
assertions resolve strictly, a green heal workflow would not prove the heal worked.
Until then this is a claim about what the healer does, not a guarantee CI enforces.

---

## Step Controls

| Field | Default | Effect |
|---|---|---|
| `when` | — | Skip the step if the condition is false |
| `retry` | `0` | Retry on failure up to N times |
| `retry_delay_ms` | `1000` | Milliseconds between retries |
| `continue_on_failure` | `false` | `true` → warn and continue; `false` → hard-stop |
| `heal` | `true` | `false` → opt this step out of the healing loop |
| `heal_assert` | — | Post-heal assertion, e.g. `{"url_contains": "/inventory"}` |
| `skip_screenshot` | `false` | Suppress the automatic post-step screenshot |
| `extra` | — | Arbitrary action config; supports `{{var}}` substitution |

Retry, `continue_on_failure` and healing are handled by `StepRunner`, not by the actions
themselves — an action's job is one attempt at one thing.

### `when` conditions

| Condition | Syntax |
|---|---|
| `context_equals` | `{ "key": "k", "value": 0 }` |
| `context_key_exists` | `"key_name"` |
| `context_greater_than` | `{ "key": "gap", "value": 0 }` |
| `context_less_than` | `{ "key": "count", "value": 10 }` |
| `context_between` | `{ "key": "count", "min": 2, "max": 8 }` |
| `url_contains` | `"/account/login"` |
| `element_exists` | `"input[name='q']"` |
| `not` / `all` / `any` | invert / AND / OR |

### Flow-level defaults

Declared once at the top; every step inherits unless it overrides. Step always wins:

```json
{
  "continue_on_failure": true,
  "steps": [
    { "action": "ol_ensure_login", "continue_on_failure": false },
    { "action": "screenshot" }
  ]
}
```

### Variables

`variables{}` are substituted at **plan time**, from the workflow's own block. Anything an
earlier step stored is substituted at **runtime**, from the `ExecutionContext` — so
`{{gap}}` resolves to the count a previous step wrote, and `{{item}}` to a value `store`
captured off the page:

```json
{ "action": "ol_collect_books",
  "when":  { "context_greater_than": { "key": "gap", "value": 0 } },
  "extra": { "limit": "{{gap}}" } }
```

A pure `"{{key}}"` reference preserves its type (int, bool); mixed strings like
`"page_{{n}}"` are string-substituted. Runtime substitution reaches `url`, `input_value`,
`element`, `extra`, `when` and `description`, and **fails the step** when the context has
no such name — unlike plan-time substitution, which leaves an unknown token alone. The
difference is where the output goes: a stray token in a log line is a nuisance, one in an
action's arguments is not.

Override any variable without touching the JSON:

```bash
python stepper/main.py run ol_regression_roundtrip \
  --vars '{"query":"Asimov","max_year":1960,"limit":2}'
```

---

## Engine Actions

Site-agnostic, registered in `build_default_registry()`:

| Action | Description |
|---|---|
| `navigate` | Go to a URL |
| `click` | Click an element via the resolver cascade |
| `fill` | Type into an input |
| `hover` | Hover (triggers CSS `:hover` menus) |
| `select` | Choose from a `<select>` by label, index or value |
| `keyboard_press` | Press a key or chord |
| `scroll_to` | Scroll an element into view |
| `wait` | Wait for a selector, URL fragment or fixed seconds |
| `screenshot` | Capture a screenshot to file |
| `store` | Write an arbitrary value into the execution context |
| `store_count` | Count elements via CSS selectors, store in context |
| `assert_count` | Assert element count matches expected |
| `assert_text` | Assert an element's text |
| `assert_visible` | Assert an element is visible |
| `extract_data` | Scrape DOM data into `context.extracted_data` |
| `paginate` | Loop pages, accumulate into `context.paginated_data` |
| `for_each_item` | Loop `context.collected_items`, run sub-steps per item |
| `ensure_login` | Generic login subflow — takes a `login_steps` list |
| `run_workflow` | Run a sub-workflow JSON, then return to the parent flow |
| `parallel` | Run `read_only` sub-steps concurrently in separate tabs |
| `measure_performance` | Collect `first_paint_ms`, `dom_content_loaded_ms`, `load_time_ms` |
| `visual_compare` | Pixel diff against a stored baseline |
| `load_test_data` | Load a JSON test-data file into `context.test_data` |

Site-specific actions (`ol_*`, `sd_*`, `pt_*`) are catalogued in
[.claude/rules/site-actions.md](.claude/rules/site-actions.md).

---

## Workflows

Sixteen ready-to-run workflows — `python stepper/main.py list` prints this table
live from disk. Run any of them from the repo root:

```bash
python stepper/main.py run <workflow-name>
```

**OpenLibrary** — `stepper/sites/openlibrary/workflows/`

| Workflow | What it showcases |
|---|---|
| `ol_search_and_add.json` | Main flow: clear → search → add → assert |
| `ol_add_only.json` | Idempotent append — no clear step |
| `ol_ensure_count.json` | Top-up to target N via `when` + `{{gap}}` |
| `ol_regression_roundtrip.json` | Full lifecycle + delta and absolute asserts |
| `ol_multi_author.json` | Two-query sequential composition |
| `ol_parallel_perf.json` | Three pages benchmarked concurrently |
| `ol_smoke_test.json` | `when`-guarded + `continue_on_failure` soft-fail |
| `ol_idempotency_test.json` | Add the same books twice → count must not grow |
| `ol_data_driven.json` | Data-driven runs via `--data testdata.json` |
| `login.json` | Reusable login subflow |

**SauceDemo** — `stepper/sites/saucedemo/workflows/`

| Workflow | What it showcases |
|---|---|
| `sd_happy_path.json` | Login → add to cart → checkout |
| `sd_multi_product.json` | Add multiple products, verify cart |
| `sd_smoke_test.json` | Smoke check with `continue_on_failure` |
| `sd_heal_test.json` | Self-healing under a changed selector |
| `sd_full_heal_flow.json` | Full heal demo — broken selectors throughout |

**phpTravels** — `stepper/sites/phptravels/workflows/` (in progress)

| Workflow | What it showcases |
|---|---|
| `hotel_booking.json` | Login → search → select → book |

---

## Examples

[`examples/plain_pom/`](examples/plain_pom/) drives the same OpenLibrary page objects
directly from pytest — no engine, no resolver, no AI. It is the counterpart to
`ol_search_and_add.json`: the same flow written imperatively.

```bash
cd examples/plain_pom && pytest tests/ -v
```

It exists to keep the POM layer honest. POMs there are constructed without `page=` or
`resolver=`, so if anything in the POM layer ever starts depending on the engine, this
suite breaks first.

The trade-off it demonstrates:

| Capability | Plain POM | Stepper workflow |
|---|---|---|
| Data-driven cases | `testdata.json` + `pytest_generate_tests` | `variables{}` in JSON |
| State between steps | a Python dict passed around | `{{gap}}` resolved at runtime |
| Conditional execution | `if` in the test body | declarative `when:` guard |
| Retry | manual `try/except` | `retry` / `retry_delay_ms` per step |
| Composition | copy-paste or a helper | `run_workflow` action |
| Parallelism | asyncio boilerplate in the test | `parallel` action |
| Screenshots / reports | manual calls | observer fires after every step |
| Broken selector | test fails | resolver cascade, then healer |

---

## Testing

```bash
# Unit — no browser, no network, no credentials. 1064 tests, ~12s.
pytest stepper/tests/unit/

# Stepper integration — real browser
pytest stepper/tests/ --ignore=stepper/tests/unit

# Plain-POM example — real browser + OpenLibrary credentials
cd examples/plain_pom && pytest tests/
```

The unit suite is browser-free as a *contract*, not a convenience. Two tests run in
subprocesses and assert that a non-browser workflow never puts Playwright into
`sys.modules`, and the suite passes unchanged with Playwright uninstalled (14 tests skip),
with no browsers installed, and with no `PLAYWRIGHT_BROWSERS_PATH` set. Tests that need to
know about a browser build own their own browsers directory rather than reading the
machine's.

CI runs the unit suite as a fast gate, then smoke workflows and integration tests against
a real browser. The mixed web+db workflow runs there too, with no network and no
credentials. See [.github/workflows/ci.yml](.github/workflows/ci.yml).

---

## Reports & Artifacts

| Artifact | Location | Generated by |
|---|---|---|
| Allure report | `reports/allure-results/` | `AllureReporter` |
| JSON report | `report.json` | `JsonReporter` |
| Test run folder | `reports/<timestamp>_<name>/` | `TestReportReporter` |
| Step results | `reports/<run>/results.json` | includes `heal_attempts` on healed steps |
| Heal suggestions | `reports/<run>/heal_suggestions.json` | `StepRunner` |
| Screenshots | `reports/<run>/screenshots/` | auto after each step |
| Run log | `reports/<run>/logs/run.log` | file log handler |
| Performance data | `artifacts/performance.json` | `measure_performance` |

```bash
allure serve reports/allure-results
```

---

## Design Principles

| Principle | Implementation |
|---|---|
| **SRP** | `StepRunner` runs steps, `ElementResolver` finds elements, `BookSearchPage` knows one page |
| **OCP** | New site = new folder + register. New action = subclass + register. No edits to existing code |
| **DIP** | `StepRunner` depends on the `ActionFactory` interface, never on a concrete action |
| **POM** | Every selector lives in a `Locators` inner class — never duplicated in JSON or glue |
| **Data-driven** | Logic is JSON, parameters are variables, env overrides config |

Patterns used and where: [.claude/rules/design-patterns.md](.claude/rules/design-patterns.md).

---

## Documentation

| Topic | Where |
|---|---|
| **Where things stand, and what is known to be wrong** | **[docs/state-of-the-stepper.md](docs/state-of-the-stepper.md)** |
| **Pointing Stepper at your own app** | **[docs/adding-your-app.md](docs/adding-your-app.md)** |
| Architecture diagrams and data flow | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Engine responsibility map | [stepper/engine/ARCHITECTURE.md](stepper/engine/ARCHITECTURE.md) |
| Working in this repo (for Claude Code) | [CLAUDE.md](CLAUDE.md) |
| POM layer rules | [.claude/rules/pom-layer.md](.claude/rules/pom-layer.md) |
| Glue layer rules | [.claude/rules/glue-layer.md](.claude/rules/glue-layer.md) |
| Three-layer contract | [.claude/rules/three-layer-contract.md](.claude/rules/three-layer-contract.md) |
| Resolver cascade | [.claude/rules/resolver-cascade.md](.claude/rules/resolver-cascade.md) |
| Site action reference | [.claude/rules/site-actions.md](.claude/rules/site-actions.md) |
| Design patterns | [.claude/rules/design-patterns.md](.claude/rules/design-patterns.md) |
| Playwright pitfalls the POMs guard against | [docs/playwright-pitfalls.md](docs/playwright-pitfalls.md) |
| How the engine stopped depending on the browser | [docs/universal-runner-plan.md](docs/universal-runner-plan.md) |
| How one run came to hold several domains | [docs/mixed-domain-plan.md](docs/mixed-domain-plan.md) |

---

## License

See [LICENSE](LICENSE).
