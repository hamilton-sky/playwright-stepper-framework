# Stepper Engine — Architecture

## Responsibility map

```
StepRunner          Iterates steps, evaluates when-guards, dispatches actions,
                    notifies observers, handles retry + continue_on_failure.
                    Knows nothing about selectors or what each action does.

ActionFactory       Registry of action_name → ActionStrategy.
                    create(name) returns the registered strategy or raises.

ActionStrategy      One action, one job. execute() is the template method and must
                    not be overridden; _execute() is the subclass slot and receives
                    page, step, resolver, context, behaviour=None.
                    Returns StepResult (status, output dict, screenshots).
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
            ├─ action.execute(page, step, resolver, ctx, behaviour)
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
  Source: the workflow's own variables{} block.
  Substituted into every step field before StepRunner sees them.
  "{{target_count}}" → 5
  Deterministic — the same JSON always produces the same StepConfig list.
  An unknown token is left alone.

Phase 2 — Run time (StepRunner._resolve_context_vars)
  Source: the ExecutionContext — counts, the generic store that `store`
  writes to, and the non-empty named fields. Anything context.get answers.
  Scope:  url, input_value, element, extra, when, description.
  "{{gap}}"  → 3      written by an earlier step
  "{{item}}" → "Dune" captured off a page by `store`
  Runs at the top of the loop, before `when` is evaluated and before the
  observers see the step, so a condition compares against the resolved
  operand and a log line matches the report.
  An unknown token FAILS the step.
```

Both phases preserve type on a pure `"{{key}}"` reference — an int stays an
int, so a later comparison behaves — and stringify an embedded one, since
there is nothing else it could become inside a sentence. Containers embed as
JSON rather than `str(...)`, which would emit Python literals nothing can parse.

**Why Phase 2 is strict where the others are forgiving.** Plan-time and
sub-step substitution leave an unknown token alone, so a typo reads as "the
name was wrong" rather than as a blank value. Phase 2 refuses, because its
output goes into an action's arguments rather than a log line. Both failures
that motivated it were silent: a literal `"{{gap}}"` reaching a POM and dying
three frames down as `'<' not supported between instances of 'int' and 'str'`,
and a literal `"{{item}}"` written to a database and then asserted against the
same literal — a check that agrees with itself and cannot fail.

A third substitution exists for sub-steps (`for_each_item`, `parallel`,
`paginate`): the dispatcher passes per-item values as a plain mapping. It
shares the walk in `runner/interpolation.py` with Phase 2 and keeps the
forgiving failure mode.

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

## Domains — what a step acts on

`StepRunner` holds no page. It holds a `SessionSet`, and per step it asks the
action which domain it belongs to and looks that domain's session up.

```
  action.domain ──► sessions.get(domain) ──► the object the action receives
       "web"                                  a Playwright Page
       "db"                                   a sqlite3 Connection
       "noop"                                 a bare object
        None                                  None — declared session-agnostic
```

Per-domain: the session, the hooks that run around a step, the `when`
vocabulary, and the preflight check. Shared across all domains: the
`ExecutionContext` below — which is how a value a browser step scraped reaches
a database step in the same run.

Sessions open on first use and close in reverse order, so a workflow that
never reaches a db step never opens a connection. A domain declares itself
from its own `sites/*/register.py`; no central file lists them.

See [../../ARCHITECTURE.md](../../ARCHITECTURE.md) for the diagram and
[../../docs/mixed-domain-plan.md](../../docs/mixed-domain-plan.md) for how it
came about.

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
       class MyAction(GlueAction):              # GlueAction, not ActionStrategy
           action_name = "xx_my_action"         # must start with the site prefix
           async def _execute(self, page, step, resolver, ctx, behaviour=None): ...

2. Wrap it in a PageModule whose register(registry) adds the action

3. Call that PageModule from sites/<site>/register.py, which main.py invokes once

4. Call the action by name in any workflow JSON:
       { "action": "my_action", "extra": { ... } }
```

No changes to the engine. Zero edits to existing code.
