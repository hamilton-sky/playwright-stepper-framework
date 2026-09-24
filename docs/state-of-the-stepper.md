# State of the Stepper

**As of `62acef0`** — the merge of M6, which completes
[`mixed-domain-plan.md`](mixed-domain-plan.md). The previous plan,
[`universal-runner-plan.md`](universal-runner-plan.md), completed at `6347371`.

This is the orientation document: what the framework is now, what changed under
it, what is verified, and what is known to be wrong. It is written to be read
before touching anything.

---

## In one paragraph

Stepper runs declarative JSON workflows. A workflow names *actions*; the engine
resolves each action, hands it whatever session its **domain** needs, and
records the result. For three of the four registered domains that session is a
Playwright `Page`; for the `db` domain it is a `sqlite3.Connection`; for `noop`
it is a bare object. The engine itself knows none of that — it knows steps,
results, retries, healing and observers. Selectors live only in POMs, flow
control lives only in workflow JSON, and the layer between them is one action,
one job.

---

## The shape

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  FLOW      stepper/sites/*/workflows/*.json                       │
  │            order, conditions, variables, loops. No selectors.     │
  └───────────────────────────────┬──────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼──────────────────────────────────┐
  │  GLUE      stepper/sites/*/pages/                                 │
  │            one action, one job. Injects page + resolver.          │
  └───────────────────────────────┬──────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼──────────────────────────────────┐
  │  POM       poms/*/pages/                                          │
  │            selectors and raw page interaction. Nothing else.      │
  └──────────────────────────────────────────────────────────────────┘

        Dependency direction: Flow → Glue → POM. Never reversed.
```

That contract is unchanged and is still the thing most worth protecting. What
changed is underneath it.

```
  ┌────────────────────────────────────────────────────────────────┐
  │  StepRunner                                                     │
  │    knows: steps, results, retry, healing, observers, hooks      │
  │    knows nothing about: browsers, pages, selectors, sessions    │
  └──────────────────────────┬─────────────────────────────────────┘
                             │  per step: "which domain is this action?"
                             ▼
                      ┌─────────────┐
                      │ SessionSet  │  lazy open, reverse-order close
                      └──────┬──────┘
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
    ┌──────────┐      ┌────────────┐      ┌──────────┐
    │   web    │      │     db     │      │   noop   │
    │   Page   │      │ Connection │      │  object  │
    └──────────┘      └────────────┘      └──────────┘

    Each domain supplies five things, all optional but session:
      session     what to open, and how to close it
      hooks       what runs around each of its steps
      shared      a handle several runs in one invocation may reuse
      conditions  its own `when` vocabulary, domain-tagged
      preflight   what is missing here, checked before anything opens
```

A domain's session is not one fixed class. `web` launches a browser, or
attaches to a running Electron app over CDP when `STEPPER_ELECTRON_CDP_PORT`
is set — same DOM, same actions, same cascade, different source for the `Page`.
Teardown differs and that is the point: a launched browser is closed, an
attached app is disconnected from and left alone.

A domain declares itself from its own folder under `stepper/sites/`.
`register_all_sites` finds it by globbing `sites/*/register.py`. **No central
file lists the domains** — adding one edits nothing outside its own directory.

---

## What is registered today

| | |
|---|---|
| Domains | `web`, `db`, `noop` |
| Actions | 68 unique instances across seven sites, plus `load_test_data` and `run_workflow`, which declare no domain and are handed no session |
| Workflows | 30, all valid (`python stepper/main.py validate`). 12 need no account, no API key and no network; two of those run bare, the other ten want one line of local setup — a loopback fixture server, a `--vars` page path, or two fixture credentials that are nobody's account |
| Unit tests | 1207, no browser / network / credentials, ~16s |
| Source | ~18,600 lines under `stepper/` + `poms/`, excluding tests |
| Tests | ~14,700 lines |

`python stepper/main.py validate` prints the domains each workflow opens:

```
  OK    sd_happy_path     6 steps  [web]
  OK    db_smoke          6 steps  [db]
  OK    db_web_mixed      8 steps  [db, web]
  OK    noop_smoke        3 steps  [noop]
```

An `OK ?` marks a workflow that is valid but whose domain is not ready on this
machine — no browser installed, a database directory that is not writable. That
distinction is deliberate: `validate` asks "is this well-formed?", which does
not depend on the machine; `run` asks "can I do this here?", and refuses.

---

## How one step is dispatched

```
  step: { "action": "db_assert_count", ... }
     │
     ├─ registry.create("db_assert_count")  ──►  action.domain == "db"
     │
     ├─ sessions.get("db")        ─► opens the connection if this is first use
     ├─ hooks["db"]               ─► that domain's hooks only
     ├─ conditions.evaluate(when) ─► routed to the db session by its own tag
     │
     └─ action.execute(connection, step, resolver, context, behaviour)
                                              │
                                    StepResult(domain="db")
```

Four things are per-domain that used to be global: the session, the hooks, the
`when` vocabulary, and the preflight. One thing is deliberately **not**: the
`ExecutionContext` is shared by every step of every domain, which is how a
value a browser step scraped reaches a database step.

Dispatchers (`for_each_item`, `parallel`, `paginate`, `ensure_login`) route
their sub-steps the same way. `parallel` refuses a whole step containing a
foreign-domain sub-step rather than doing half its work.

---

## What landed, and where to read about it

Both plans carry a "as landed" section per ticket describing what actually
shipped and where it deviated from the proposal. They are the real record.

**[`universal-runner-plan.md`](universal-runner-plan.md)** — made the engine
domain-free. `StepHook`, `NullResolver`, the `Domain` registry, per-domain
`when` conditions, the driver factory, and `_noop`: a domain with no browser,
no resolver and no POMs, whose test asserts Playwright never reaches
`sys.modules`.

**[`mixed-domain-plan.md`](mixed-domain-plan.md)** — made one run hold several
domains. `SessionSet` with lazy open and reverse-order close, per-domain hooks
and conditions, sub-step routing, plan-time domain discovery and preflight,
and the `db` domain that proved the abstraction was not browser-shaped.

---

## What is verified, and how

Every ticket in both plans was checked four ways, because each catches
something the others cannot:

1. **The unit suite** — 1207 tests, no browser, no network, no credentials.
2. **The suite with Playwright made unimportable** — 1193 pass, 14 skip. This
   is what proves the engine does not secretly depend on it.
3. **The suite with no browsers installed** — the condition CI's Unit Tests job
   actually runs in. It caught a round of tests that read the machine's real
   browsers directory and so passed locally and failed in CI.
4. **A real browser run** — because none of the above notices that a resolver
   silently stopped matching.

CI runs the db-only workflow in the unit job and the mixed web+db workflow in
the integration job, both with no network and no credentials.

---

## Known gaps

Listed because they are real, not because they are planned.

### ~~1. Runtime variable substitution is narrower than documented~~ — fixed

Kept here because the shape of the bug is worth remembering.

Substitution ran in two passes, and the run-time one was limited on two axes at
once: it read `context.counts` only, and walked `step.extra` only. `store` —
the action a browser step uses to capture a value off a page — writes the
context's *generic* bucket, so the natural mixed-domain workflow (scrape a
value, write it through SQL) could not pass that value along. The documentation
beside it described a wider pass under a name, `_resolve_context_vars`, that
did not exist; the real method was `_resolve_count_vars`.

Both limits failed the same way: the literal string `"{{name}}"` arriving at an
action as an argument and dying somewhere that named neither the step nor the
reference.

It now reads whatever `context.get` answers and walks every data field —
`url`, `input_value`, `element`, `extra`, `when`, `description` — and refuses
to dispatch a step carrying a name the context cannot answer. The walk is
shared with sub-step substitution and the db domain's parameter binding, in
`stepper/engine/runner/interpolation.py`.

One thing worth recording about how it was built. The first version resolved
inside `_run_step`, which runs *after* `when` is evaluated and after the
observers fire — so a condition compared against the literal `"{{v}}"` and
skipped its own step, and the start log printed a token the report did not
contain. Every field-level unit test passed. Only a runner-level test caught
it, which is why there are now five.

### 2. `db_execute` runs unvalidated SQL from workflow JSON

Values are bound, so there is no injection through *data*. The statement itself
is whatever the workflow says. Reasonable for a test framework whose workflows
are authored by the person running them, but it should be a decision rather
than an accident.

### 3. Preflight under-reports as root

`os.access` is generous to root, so a container running as root gets silence
where an ordinary user would get a warning. Deliberate — a false "not ready"
blocks a run that would have worked — but it means the check is weakest in the
environment most CI-adjacent tooling runs in.

### 4. Every domain was written by one author, in one week

`web`, `db` and `noop` all exist to exercise the abstraction rather than
because someone needed them. M6 found three bugs within an hour of a genuinely
different domain existing, each having survived several tickets because `noop`
was too weak to exercise it. A domain written by someone else — AWS, HTTP, a
message queue — would likely find more.

---

## Where things live

```
  poms/                        selectors and raw page interaction
    shared/                    Locator, BasePage, driver, interfaces
  stepper/
    main.py                    composition root — plan, preflight, open, run
    bootstrap/                 Domain registry, WebSession, settings, infra
    engine/
      actions/                 basic / assertions / data / flow / measurement
      resolvers/               the cascade, and NullResolver
      runner/                  StepRunner, hooks, when_eval
      planner/                 JSON planner, validator, domain discovery
      reporter/                observers and the report manager
      session.py               SessionAdapter, NullSession, SessionSet
    sites/
      openlibrary/ saucedemo/ phptravels/    browser sites
      db/                                     SQLite — the non-browser domain
      _noop/                                  the engine's honesty test
  examples/plain_pom/          POMs with no engine and no resolver
  docs/                        this file, the two plans, and the guides
```

[`docs/exam-submission.md`](exam-submission.md) is the original design
narrative from the project's first week — a historical document, preserved as
written, and the only place that records *why* the framework is shaped this way
rather than what it currently does.

Rule files under `.claude/rules/` are the per-area contracts; read the one for
the layer you are changing before changing it. [`CLAUDE.md`](../CLAUDE.md)
routes between them.
