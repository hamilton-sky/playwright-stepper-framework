# Stepper Engine — Architecture

## Responsibility map

```
StepRunner          Iterates steps, evaluates when-guards, dispatches actions,
                    notifies observers, handles retry + continue_on_failure.
                    Knows nothing about selectors or what each action does.

ActionFactory       Registry of action_name → ActionStrategy.
                    create(name) returns the registered strategy or raises.

ActionStrategy      One action, one job. _execute() receives page, step, resolver,
                    context. Returns StepResult (status, output dict, screenshots).
                    output dict is persisted to results.json via reporter.
                    Never imports from runner/.

ElementResolver     10-stage cascade: Role → Label → Placeholder → Text → Id →
                    CSS → XPath → Semantic → VisualAI.
                    Injected into POMs at runtime; POMs never import it directly.

ReporterStrategy    CompositeReporter fans out to Console, JSON, Allure, TestReport.
                    StepRunner calls record_step() — never knows what reporters exist.

StepObserver        on_step_start / on_step_done / on_log.
                    LoggingObserver and CallbackObserver ship with the engine.
                    UI layers (Tkinter, Streamlit) plug in via CallbackObserver.

JsonFilePlanner     Loads a workflow JSON file:
                    1. Resolves variables{} into all step fields (plan time).
                    2. Applies flow-level defaults (e.g. continue_on_failure).
                    3. Returns list[StepConfig] — runner never reads raw JSON.

when_eval           Condition evaluator called by StepRunner before each step.
                    Returns True (run) or False (skip).
```

---

## Execution flow

```
main.py
  │
  ├─ JsonFilePlanner.plan()          load JSON, substitute variables{}, apply defaults
  │       │
  │       └─ list[StepConfig]
  │
  └─ StepRunner.run(steps, context)
          │
          for each step:
            ├─ evaluate_when(step.when, ctx, page)   → skip if False
            ├─ _resolve_context_vars(step, ctx)       → runtime {{key}} substitution
            ├─ ActionFactory.create(step.action)      → ActionStrategy
            ├─ action.execute(page, step, resolver, ctx)
            │       └─ writes to ExecutionContext (collected_items, counts, …)
            ├─ auto-screenshot
            ├─ reporter.record_step(result)
            ├─ observers.on_step_done(result)
            └─ continue_on_failure check / hard-stop
```

---

## Two-phase variable resolution

```
Phase 1 — Plan time (JsonFilePlanner)
  variables{} block substituted into all step fields before StepRunner runs.
  "{{target_count}}" → 5
  Deterministic — same JSON always produces same StepConfig list.

Phase 2 — Runtime (StepRunner._resolve_context_vars)
  context.counts keys substituted just before each step executes.
  "{{gap}}" → 3   (value written by ol_ensure_count earlier in the same run)
  Pure "{{key}}" reference preserves original type (int, bool).
  Mixed string "page_{{n}}" is string-substituted.
```

---

## when-condition reference

```
context_equals        { key, value }          exact equality
context_key_exists    "key_name"              set + non-empty
context_greater_than  { key, value }          numeric  >
context_less_than     { key, value }          numeric  <
context_between       { key, min, max }       inclusive range
url_contains          "fragment"              current page URL
element_exists        "css selector"          live DOM check
not / all / any       composable              invert / AND / OR
```

---

## Step-level controls

| Field | Default | Resolved at |
|---|---|---|
| `when` | — | runtime, before each step |
| `retry` | `0` | runtime, retry loop |
| `retry_delay_ms` | `1000` | runtime, retry loop |
| `continue_on_failure` | `false` | runtime, after each step |

Flow-level `continue_on_failure: true` is inherited by all steps at **plan time**.
Per-step value always wins over the flow default.

```
flow-level: true   →  all steps soft-fail by default
step-level: false  →  that specific step hard-stops (e.g. ol_ensure_login)
```

---

## ExecutionContext — shared state between steps

```python
context.collected_items   # list[str]  — URLs collected by ol_collect_books
context.counts            # dict       — numeric signals between steps
context.extracted_data    # any        — output of extract_data action

context.set_count("gap", 3)   # written by ol_ensure_count
context.get("gap")            # read by when-guard + resolved into {{gap}}
```

Context is created once per run and passed through the entire step list.
Actions communicate exclusively through context — never via return values.

---

## Adding a new site

```
1. Create sites/<site>/pages/<action>.py
       class MyAction(ActionStrategy):
           action_name = "my_action"
           async def _execute(self, page, step, resolver, ctx): ...

2. Create sites/<site>/pages/__init__.py  (register via PageModule)

3. Import the module in main.py (or auto-discover via register_all_pages())

4. Call the action by name in any workflow JSON:
       { "action": "my_action", "extra": { ... } }
```

No changes to the engine. Zero edits to existing code.
