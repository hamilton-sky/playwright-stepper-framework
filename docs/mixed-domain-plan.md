# Mixed-domain workflows — a browser step and a database step in one file

**Status:** M1, M2 and M3 are implemented. M4–M6 are still proposal, verified
against `6347371` (the merge of the universal-runner work).

The four open questions in §9 are settled — see each one. Routing is live:

```
  passed   domain=web   'web: open the page'
  passed   domain=noop  'noop: store a count'
  passed   domain=web   'web: log in button'
  Result: 6/6 passed  (0 failed)      # one real Chromium launch
```

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

Engine actions declare it themselves. The audit said 20 web and 3 agnostic.
**It was wrong, and the correction matters:**

```
  domain = "web"   21 actions   navigate click fill hover select screenshot
                                wait  scroll_to keyboard_press assert_* store*
                                extract_data measure_performance visual_compare
                                ensure_login paginate parallel for_each_item
  domain = None     2 actions   load_test_data  run_workflow
```

`wait` looks session-free — one branch is a bare `asyncio.sleep(2)` — but the
other calls `_wait_for(page, target)` for a selector or URL fragment. Declaring
it agnostic would hand it `None` and break every
`{"action": "wait", "wait_for": "..."}` step in the tree. This is exactly what
§9 Q1 meant by "audit the three before choosing", and it is now pinned by
`test_wait_is_a_web_action_despite_appearances`.

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
| **M1** | Actions declare a domain — **LANDED** | low | No behaviour change; a single-domain run is unaffected |
| **M2** | `SessionSet`, lazy open, close-all — **LANDED** | medium | `StepRunner` takes it *alongside* one session |
| **M3** | Hooks and conditions per domain — **LANDED** | medium | 5.3 is a bug fix; 5.4 revisits T4's signature |
| **M4** | Dispatchers route sub-steps | medium-high | `parallel` tabs mode must refuse cross-domain |
| **M5** | Plan-time domain discovery | low | `validate` reports the domains a workflow needs |
| **M6** | The receipt: a real second domain | low | See below |

### M1 and M2, as landed

`ActionStrategy.domain` defaults to `None`, so a new engine action that forgets
to declare one fails loudly rather than inheriting the browser by accident.
`PageModule.register_actions()` — the funnel T5 built — stamps `cls.domain`
onto every glue action, so a site action never repeats what its page declares
and cannot drift from it.

`SessionSet` lives in `engine/session.py` beside `SessionAdapter`. Opening is
lazy and cached, closing is reverse-order through nested finallys, and
`get(None)` returns `None` — the agnostic contract from §9 Q1.

`StepRunner` gained `sessions=` **without losing `page=` or `session=`**. A
single already-open session is wrapped by `SessionSet.single()`, which answers
*every* domain with that one object — precisely how the loop behaved before
routing existed. That is why all 912 pre-existing tests passed with no test
file edited. `_page` became a property reading the primary session, so the heal
loop and the `when` evaluator are unchanged until M3 moves them.

`build_session_set()` builds an adapter for *every* registered domain and
opens none. `build_pipeline` opens the primary eagerly — the browser launches
at the same moment it always did — and `adopt()`s it so the set is the single
owner. `run()` and `run_data_rows()` now close the set rather than one session,
which removes the double-owner problem rather than working around it.

One thing the ticket did not anticipate: a workflow naming a step from another
domain used to work by accident (every action got the one session). Building
the set from *all* registered domains keeps that working, and now correctly —
`noop_set` receives a `NullSession` rather than a Playwright `Page`.

**Verified:** 946 unit tests pass, up from 912, with no existing test modified;
945 pass and 1 skips with Playwright made unimportable. A real Chromium run of
a six-step workflow mixing web and noop steps passes 6/6 with one launch, and
`run_data_rows` still shares one browser across two rows.

### M3, as landed

**Hooks are a dict keyed by domain, and only a dict.** A flat list was
considered and rejected: a list meaning "every step" *is* the defect this
ticket removes, so accepting one would keep the footgun in the API for callers
that no longer exist. `main.py` is the only production caller; the churn was
two test files whose doubles now declare a domain, which they should have all
along since they test domain-routed dispatch.

`None` is a key like any other, which is why M3 needs no separate "global
hooks" bucket: hooks for session-agnostic steps go under `{None: [...]}`, and
the dispatch rule stays one sentence — *a step runs its own domain's hooks*.
Nothing in the tree wants one; `StepObserver` is already the seam for
cross-cutting logging and timing.

**Conditions carry a domain, tagged at registration** —
`registry.register("url_contains", url_contains, domain="web")`. The registry
resolves the session before calling, so an evaluator's signature stays
`(session, spec, context)`, the one T4 settled. `evaluate()` accepts a bare
session as well as a `SessionSet` and wraps it, so sub-step dispatch (still
unrouted until M4) and every existing test keep working.

One gap found while verifying: `StepResult.domain` existed but the reporter
never serialized it, so §9 Q3's stated benefit — *"makes a mixed-run report
readable"* — was not actually delivered. `results.json` now carries `domain`
on each step, omitted when the run is single-domain and every row would say
the same thing.

**Verified** against a real browser, where the fix is visible as an artifact
rather than an assertion:

```
  status   domain  screenshots                step
  passed   web     step_01_navigate.png       web: open the page
  passed   noop    — none —                   noop: store a count
  passed   web     step_03_click.png          web: log in button
  passed   noop    — none —                   noop: read the count back
  passed   web     step_05_assert_text.png    web: url_contains + context in one when
```

The noop steps got no screenshot because the web domain's `ScreenshotHook`
never ran for them. Before M3 it ran, called `session.screenshot(...)` on a
non-page, and swallowed the error — silence rather than a failure. The last
step's `when` combines `url_contains` (needs the web session) with
`context_greater_than` (needs none) in one clause.

961 unit tests pass, up from 947; 960 pass and 1 skips with Playwright made
unimportable.

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

1. ~~**What does a session-agnostic action receive?**~~ **Settled: `None`.**
   The audit it asked for changed the answer's scope — `wait` turned out to
   need a session, so only two actions are agnostic, not three. See 5.1.
2. ~~**Is `domain` on the action, or on the step?**~~ **Settled: the action**,
   stamped onto glue actions from their `PageModule`. One fact in one place.
3. ~~**Should `StepResult` record the domain?**~~ **Settled: yes.**
   `StepResult.domain` is additive and gives the routing tests something
   concrete to assert rather than infer.
4. **What happens when a workflow names a domain whose credentials are
   missing?** Fail at plan time with the domain named, not at first use.
   *Still open — it belongs to M5.* M2 does the runtime half: an unregistered
   domain raises `UnknownDomainError` naming it and listing what the run has.

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
