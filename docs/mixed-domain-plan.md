# Mixed-domain workflows — a browser step and a database step in one file

**Status:** proposal. Nothing here is implemented. Verified against `6347371`
(the merge of the universal-runner work).

The goal is one workflow that logs in through the UI, then asserts the row
landed in the database — or calls an AWS API, or checks an HTTP endpoint —
with the steps sharing one `ExecutionContext` and one report.

This builds directly on [`universal-runner-plan.md`](universal-runner-plan.md),
whose §9 Q1 deliberately scoped this out. That question is now the work.

---

## 0. Start from what already works

The first thing to establish is what is actually missing, because it is less
than the previous plan's scope note implies. This runs **today**, unmodified:

```json
{ "steps": [
  { "action": "navigate",  "description": "web: open the page", "url": "..." },
  { "action": "noop_set",  "description": "noop: store a count",
    "extra": { "key": "widgets", "value": 7 } },
  { "action": "assert_text", "description": "web: read the page", "...": "..." },
  { "action": "click",     "description": "web: click, gated on the noop value",
    "when": { "context_greater_than": { "key": "widgets", "value": 5 } } }
]}
```

```
  Result: 5/5 passed  (0 failed)
```

Two things in the tree make that work, and neither needs changing:

- **One action registry holds every domain.** `sd_login` and `noop_set` are
  registered side by side — there is no per-domain registry to bridge.
  Verified: 42 actions, one `ActionRegistry`.
- **`ExecutionContext` is domain-agnostic**, so values cross the boundary for
  free. The `when` clause above reads a counter a non-web step wrote.

### So what is missing

Exactly one thing. `StepRunner` holds **one** session and hands it to every
action (`step_runner.py`, in `_run_retry_loop`):

```python
result = await action.execute(self._page, step, self._resolver, ctx, self._behaviour)
```

`noop_set` works inside a web run because it ignores that argument. A database
action needing a live connection would be handed a Playwright `Page`.

> **The unsupported case is not "mixed workflows". It is "a step whose action
> needs a session of its own".** Everything below is about routing sessions,
> not about mixing.

---

## 1. Today's shape

```
                        ┌──────────────────┐
                        │   workflow JSON  │
                        └────────┬─────────┘
                                 ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                         StepRunner                            ║
  ║                                                               ║
  ║   self._page        ─────────────┐                            ║
  ║   self._hooks       ───────────┐ │                            ║
  ║   self._conditions  ─────────┐ │ │                            ║
  ╚══════════════════════════════╪═╪═╪════════════════════════════╝
                                 │ │ │
        every step ──────────────┘ │ │   one vocabulary, one session
        every step ────────────────┘ │   every hook, every step
        every step ──────────────────┘   ONE session, every action
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  action.execute(page…) │
                    └────────────────────────┘
```

One session, one hook list, one condition registry — chosen once by
`RunConfig.domain` and applied uniformly. A step cannot ask for anything else.

---

## 2. The proposed shape

```
                        ┌──────────────────┐
                        │   workflow JSON  │
                        └────────┬─────────┘
                                 ▼
  ╔══════════════════════════════════════════════════════════════╗
  ║                         StepRunner                            ║
  ║              (still knows no domain at all)                   ║
  ║                                                               ║
  ║   self._sessions : SessionSet                                 ║
  ║   self._hooks    : {domain -> [StepHook]}                     ║
  ║   self._conditions : ConditionRegistry (domain-tagged)        ║
  ╚═══════════════════════════╤══════════════════════════════════╝
                              │  per step, ask the action
                              ▼
                  ┌───────────────────────────┐
                  │  action.domain  ──────────┼──► "web" │ "db" │ None │ set
                  └───────────┬───────────────┘
                              ▼
  ┌──────────────────────── SessionSet ──────────────────────────┐
  │                                                               │
  │   "web" ──► WebSession      ──► Playwright Page   (lazy)      │
  │   "db"  ──► SqliteSession   ──► Connection        (lazy)      │
  │   "aws" ──► AwsSession      ──► boto3 client      (lazy)      │
  │                                                               │
  │   get(domain) opens on first use and caches                   │
  │   close_all() closes in reverse open order                    │
  └───────────────────────────────────────────────────────────────┘
```

The runner gains no domain knowledge. It gains a *lookup*: the step names an
action, the action names a domain, the `SessionSet` hands back that domain's
session.

---

## 3. How one step is dispatched

```
   step {"action": "db_assert_row", "when": {...}}
        │
        ▼
   registry.create("db_assert_row")  ──► action
        │
        ├─ action.needs_session_set ? ──── yes ──► pass the whole SessionSet
        │                                          (dispatchers only:
        │                                           for_each_item, parallel,
        │                                           ensure_login, paginate,
        │                                           run_workflow)
        │
        └─ no
             │
             ▼
        action.domain
             │
        ┌────┴────────────────┬───────────────────────┐
        ▼                     ▼                       ▼
     "db"                  "web"                    None
        │                     │                       │
        ▼                     ▼                       ▼
  sessions.get("db")   sessions.get("web")          None
        │                     │                       │
        ▼                     ▼                       ▼
  hooks["db"]           hooks["web"]              no hooks
  (none)                (captcha, screenshot)
        │                     │                       │
        └─────────────────────┴───────────────────────┘
                              ▼
              action.execute(<that session>, step, …)
```

Three categories, and the third is the one that keeps today's behaviour intact:

| `domain` | Means | Gets | Examples |
|---|---|---|---|
| `"web"`, `"db"`, … | Needs that domain's session | that session | `click`, `sd_login`, `db_assert_row` |
| `None` | Session-agnostic | `None` | `wait`, `load_test_data`, `noop_set` |
| *(dispatcher flag)* | Routes sub-steps itself | the whole `SessionSet` | `for_each_item`, `parallel` |

---

## 4. Lifecycle — open late, close everything

```
  plan time            run time                         teardown
  ─────────            ────────                         ────────

  validate_plan        step 1  navigate   ─► open web ──┐
    │                  step 2  db_assert  ─► open db  ──┤
    ├─ resolve every   step 3  navigate   ─► (cached)   │
    │  action                                           │
    ├─ collect their   step 4  s3_put     ─► open aws ──┤
    │  domains                                          │
    │  {web, db, aws}                                   │
    │                                                   ▼
    └─ refuse unknown                        close_all(), reverse order:
       domains here,                           aws ► db ► web
       before anything                       each guarded — one failure
       is opened                             must not strand the rest
```

Two properties worth stating plainly:

- **A db-only workflow never launches a browser.** Sessions open on first use,
  so the domains a workflow does not touch cost nothing.
- **Validation happens before any session opens.** `PlanValidator` already
  resolves every action, so it already knows the domain set; naming an
  unregistered domain should fail there, exactly as an unknown `when`
  condition now does.

---

## 5. What changes, concretely

Six seams. Four are mechanical; two carry the design risk.

### 5.1 Actions declare a domain — *nearly free*

`PageModule.domain` already exists (added by the universal-runner work's T8),
and `PageModule.register_actions()` is the single funnel every glue action
passes through — all 13 site `register()` methods go through it. Stamping the
domain there covers every site action in one line:

```python
# base_page_module.py, inside register_actions()
action.domain = cls.domain          # "web" by default; "db" for a db module
```

Engine actions declare it themselves. From an audit of the 23:

```
  domain = "web"   20 actions   navigate click fill hover select screenshot
                                scroll_to keyboard_press assert_* store*
                                extract_data measure_performance visual_compare
                                ensure_login paginate parallel for_each_item
  domain = None     3 actions   wait  load_test_data  run_workflow
```

### 5.2 `SessionSet` — the new object

```python
class SessionSet:
    def __init__(self, domains: dict[str, Domain], cfg, settings, reporter): ...
    async def get(self, name: str | None) -> object | None: ...   # lazy, cached
    async def close_all(self) -> None: ...                        # reverse order
```

One `SessionAdapter` per domain, opened on first `get()`. `close_all` mirrors
`WebSession.close`'s nested-finally shape: every session still closes when an
earlier one raises, and the first failure still propagates.

### 5.3 Hooks become per-domain — *a real bug fix*

Today every hook runs for every step. In a mixed run that means
`ScreenshotHook` would try to screenshot a database connection. It swallows the
error, so you would get **silence, not a failure** — the exact failure mode the
universal-runner work existed to remove. `Domain.hooks` already exists; the
runner just needs `{domain: [hooks]}` and to run the step's own bucket.

### 5.4 Conditions get a domain tag — *changes a signature settled last week*

`url_contains` needs the web session; a `db_row_exists` would need the db one.
A single `when` can name both:

```json
{ "all": [ { "url_contains": "/receipt" },
           { "db_row_exists": { "table": "orders", "id": "${context.order_id}" } } ] }
```

**Recommended:** tag the evaluator at registration and let the registry look up
the session, so the evaluator signature stays `(session, spec, context)`:

```python
registry.register("url_contains", url_contains, domain="web")
```

**Rejected alternative:** pass the whole `SessionSet` to every evaluator. It
works, but it makes every core predicate take an object it must not use, and it
changes a signature that ticket T4 only just settled.

### 5.5 Dispatchers route their sub-steps

`for_each_item`, `ensure_login`, `paginate`, `parallel` and `run_workflow`
forward their session to sub-steps. They need the `SessionSet` instead, so each
sub-step is routed by its own action's domain.

`run_workflow` is the easy one — it re-enters `StepRunner.run` through the
callable bound at `build_pipeline`, so it inherits routing for free.

`parallel` is the awkward one. Its `tabs` mode reaches for `page.context`:

```python
browser_context = page.context        # flow.py, _run_tabs
```

That is browser-only by construction. It should **refuse a non-web sub-step
with a clear message** rather than fail obscurely on a missing attribute —
the pattern `flow.py` already uses when `isolated_browser` has no launcher.

### 5.6 Healing gets gated on the domain

The heal loop calls `VisualBridge.check(self._page, …)` and
`DOMSnapshotCascade.capture(self._page, …)`. Healing a failed database
assertion is meaningless, and pointing a DOM snapshot at a connection object is
the silent-no-op failure mode again. Heal should run only for steps whose
domain supplies a resolver — which is the web domain and, by design, only it.

---

## 6. Work plan

```
  M1 ──► M2 ──► M3 ──► M6         critical path: 4
          │      │      ▲
          │      └► M4 ─┤
          └────────► M5─┘
```

| | Ticket | Risk | Note |
|---|---|---|---|
| **M1** | Actions declare a domain | low | No behaviour change; a single-domain run is unaffected |
| **M2** | `SessionSet`, lazy open, close-all | medium | `StepRunner` takes it in place of one session |
| **M3** | Hooks and conditions per domain | medium | 5.3 is a bug fix; 5.4 revisits T4's signature |
| **M4** | Dispatchers route sub-steps | medium-high | `parallel` tabs mode must refuse cross-domain |
| **M5** | Plan-time domain discovery | low | `validate` reports the domains a workflow needs |
| **M6** | The receipt: a real second domain | low | See below |

### M6 should be SQLite, not AWS

`sqlite3` is in the standard library. A `db` domain built on it needs no new
dependency, no credentials and no network, so the proof workflow — *write a row
through the UI, assert it through SQL* — runs in CI hermetically, the way
`_noop` does now. An AWS domain is a better demo and a worse test.

---

## 7. Compatibility guarantees

1. **Every shipped workflow runs unmodified.** They are all single-domain; a
   single-domain run resolves every step to the same session it gets today.
2. **No `ActionStrategy` subclass needs editing** beyond adding a class
   attribute, and glue actions need not even do that (5.1).
3. **The three-layer contract is untouched.** POMs stay web-only.
4. **CLI unchanged**, plus `validate` gaining a line about domains.

One deliberate exception: **hooks stop running for steps outside their domain**
(5.3). In a single-domain run that is a no-op.

---

## 8. Non-goals

- Parallel execution *across* domains. Steps stay ordered; `parallel` stays
  within one domain.
- A transaction or rollback model spanning domains. If a web step succeeds and
  a db step fails, the run reports that — it does not undo anything.
- Connection pooling, retries or credential management beyond what a domain's
  own `SessionAdapter` chooses to do.
- Building an AWS domain (see M6).

---

## 9. Open questions to settle before M1

1. **What does a session-agnostic action receive — `None`, or the "primary"
   session?** Recommend `None`: an action that declared it needs nothing should
   not silently come to depend on something. But it is a behaviour change for
   any action that currently ignores `page` *by accident*, so audit the three
   in 5.1 before choosing.
2. **Is `domain` on the action, or on the step?** `StepConfig.extra` could
   carry `"domain": "db"` per step, which needs no action changes at all — but
   it moves a fact about the *action* into every workflow that uses it, and
   lets two workflows disagree about what `db_assert_row` acts on.
   Recommend the action.
3. **Should `StepResult` record which domain a step ran against?** Cheap, and
   it makes a mixed-run report readable. Probably yes; it is additive.
4. **What happens when a workflow names a domain whose credentials are
   missing?** Fail at plan time with the domain named, not at first use.

---

## Appendix — how to re-verify §0

```bash
# All domains already share one registry
python -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from stepper.engine.actions.factory import build_default_registry
from stepper.bootstrap.infra import register_all_sites
r = build_default_registry(); register_all_sites(r, Path('stepper'))
print(len(r.names()), 'actions in one registry')
print([n for n in r.names() if n.startswith(('noop_','sd_'))])"

# The single session, threaded to every action
grep -n "action.execute(self._page" stepper/engine/runner/step_runner.py

# What parallel's tabs mode assumes
grep -n "page.context" stepper/engine/actions/flow.py
```
