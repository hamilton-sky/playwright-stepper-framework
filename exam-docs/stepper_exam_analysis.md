# Stepper Framework — Exam Analysis

## What the Stepper Is

The Stepper is a JSON-driven browser automation engine built on top of Playwright + Python.
It sits above the POM layer and replaces hand-written orchestration code with declarative
workflow files. A workflow is a JSON array of named steps; the engine handles retries,
conditional branching, context passing, and reporting without any test code changes.

```
JSON Workflow  →  StepRunner  →  GlueAction  →  POM  →  Playwright  →  Browser
(WHAT to do)      (HOW to run)   (bridge)        (WHERE elements are)
```

---

## How the Stepper Solves the Exam

The exam requires four capabilities: search, add, assert, and measure performance.
The Stepper delivers all four through a single workflow file.

### 1. Search — `ol_collect_books`

`ol_search_and_add.json` calls `ol_collect_books` with `query`, `max_year`, and `limit`
as variables. The glue action delegates to `BookSearchPage.collect_books_under_year()`,
which paginates automatically until `limit` books are found or pages run out.
Results land in `context.collected_items` for the next step to consume.

### 2. Add — `ol_add_to_shelf`

`ol_add_to_shelf` iterates `context.collected_items` and calls
`BookDetailPage.add_to_reading_list()` for each URL. A screenshot is captured after
every book — no extra code needed.

### 3. Assert — `ol_assert_count`

`ol_store_count` captures the shelf count before adding. `ol_assert_count` compares
the new count against `count_before + delta`. If the numbers don't match, the step
hard-stops and the entire workflow fails with a clear error message.

### 4. Performance — `measure_performance`

The `measure_performance` built-in action collects `first_paint_ms`,
`dom_content_loaded_ms`, and `load_time_ms` via the browser Performance API.
Results are written to `artifacts/performance.json` and the run report.

### Full exam flow in one workflow

```json
// ol_search_and_add.json (simplified)
{
  "variables": { "query": "Dune", "max_year": 1980, "limit": 5 },
  "steps": [
    { "action": "ol_ensure_login" },
    { "action": "ol_clear_reading_list" },
    { "action": "ol_store_count",   "extra": { "context_key": "count_before" } },
    { "action": "ol_collect_books", "extra": { "query": "{{query}}", "max_year": "{{max_year}}", "limit": "{{limit}}" } },
    { "action": "ol_add_to_shelf" },
    { "action": "ol_assert_count",  "extra": { "delta": "{{limit}}" } }
  ]
}
```

Run it with:
```bash
python stepper/main.py --workflow sites/openlibrary/workflows/ol_search_and_add.json
```

Override any variable without editing the file:
```bash
python stepper/main.py --workflow ... --vars '{"query":"Foundation","limit":3}'
```

---

## What the Stepper Does Well

### Smart element resolution — the resolver cascade

Every click and fill goes through a three-phase cascade before touching the DOM:

1. **Deterministic** — tries ARIA role, label, placeholder, text, id, CSS, XPath in
   priority order. Stops at the first unique match.
2. **Semantic** — if no unique match, embeds the element description with MiniLM-L6-v2
   and scores candidates by cosine similarity (threshold 0.80).
3. **AI pick** — if still ambiguous, asks Groq → Gemini → Claude to choose the best
   candidate.

This means tests survive UI redesigns as long as ARIA roles and labels stay consistent —
no test rewrite needed for a CSS class rename.

### Declarative conditional flows

`when:` guards on any step enable branching without Python code:

```json
{ "action": "ol_collect_books",
  "when": { "context_greater_than": { "key": "gap", "value": 0 } },
  "extra": { "limit": "{{gap}}" }
}
```

The "top-up" workflow (`ol_ensure_count.json`) uses this to add only the books needed
to reach a target count — zero imperative logic.

### Per-step retry

```json
{ "action": "ol_add_to_shelf", "retry": 3, "retry_delay_ms": 2000 }
```

Flaky network clicks no longer fail the entire run.

### Multi-site with zero engine changes

Adding SauceDemo required only: new POM files, new glue actions, and new workflow JSONs.
The engine, resolver, runner, and reporters are untouched. This is Open/Closed in
practice — extend by adding files, not by editing existing ones.

### Rich reporting out of the box

Every run produces:
- Console summary
- `report.json` with step-level results
- `reports/<timestamp>-<name>/index.html` with screenshots and logs
- Allure-compatible XML for `allure serve`

All reporters fire automatically via the Observer pattern — no calls in test code.

### Data-driven without test duplication

```bash
python stepper/main.py --workflow ol_search_and_add.json \
  --data poms/openLibrary/data/testdata.json
```

This runs the same workflow once per row in `testdata.json`, sharing one browser
instance for speed.

---

## Where the Stepper Falls Short

### Debugging JSON workflows is harder than debugging Python

When a workflow step fails, the stack trace points into the engine internals, not into
the workflow file. Finding _which_ step failed and _why_ requires reading the console
output or `report.json`. There is no debugger-friendly "step into" for JSON.

### No static typing or schema validation on workflow files

A typo in an action name (`"ol_colect_books"`) is silently ignored until runtime.
There is no JSON Schema file that IDEs or CI can validate against before a run.

### Context is a flat dict — no namespacing

All steps share one `context` dict. Two actions that both write `context["count"]`
will silently overwrite each other. At scale this becomes fragile.

### The resolver cascade adds latency on ambiguous elements

Phase 2 (semantic embedding) and Phase 3 (AI API call) can add hundreds of
milliseconds per element when the deterministic phase fails. For a 50-step workflow
hitting ambiguous elements, this accumulates.

### AI resolver requires external API keys

Phases 2 and 3 depend on sentence-transformers (local) and Groq/Gemini/Claude (remote).
In offline environments or when API keys are missing, the cascade falls back to the
top semantic result — which may be wrong without explicit CSS or XPath fallbacks in
the cfg list.

### phpTravels integration is scaffolded but incomplete

POM files exist under `poms/phpTravels/` but there are no glue actions registered in
`main.py` and no workflows under `stepper/sites/phptravels/workflows/`. The site cannot
run end-to-end without wiring these up.

### ClaudePlanner (natural language mode) is experimental

`--task "search Dune and add 5 books"` generates steps via the Claude API, but the
quality depends on prompt tuning and model availability. It is not suitable for
reliable CI pipelines.

### No parallelism across workflow files

The `parallel` action runs read-only sub-steps concurrently within one workflow, but
there is no built-in way to run two independent workflows simultaneously and merge
their results.

---

## Summary

| Capability | Strength | Limitation |
|---|---|---|
| Element resolution | 3-phase cascade survives UI churn | AI phase adds latency + requires keys |
| Orchestration | JSON workflows, no Python boilerplate | Hard to debug, no schema validation |
| Retry / resilience | Per-step retry out of the box | — |
| Conditional flows | `when:` guards, context-driven | Flat context dict, no namespacing |
| Reporting | Automatic, multi-format | — |
| Multi-site | Add files, never edit engine | phpTravels not fully wired |
| Data-driven | `--data` flag, one browser shared | — |
| Natural language | `--task` experimental mode | Not CI-safe |
