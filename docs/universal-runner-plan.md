# Universal Runner — making the stepper domain-free

**Status:** T1, T2 and T3 are implemented — the spine is done. T4–T8 are still
proposal, verified against the tree at `69d720f`.

The goal is that `StepRunner` runs any domain behind an adapter, with the
browser demoted from "the core" to "the first adapter".

> **This revision is the audited one.** An earlier draft closed its list of
> leaks at seven and called a non-browser run impossible today. The seven are
> all real, but the list was not complete and the impossibility claim was
> false. Every line reference below was re-checked against `69d720f`, three
> further leaks were found (L8–L10), three tickets were re-scoped because they
> collide with tests that already exist, and one new ticket (T7) was added as a
> prerequisite for the plan's own acceptance criterion. §0 lists what changed
> and why.

---

## 0. What the audit changed

| Original claim | Finding |
|---|---|
| "A non-browser workflow running to completion is currently impossible" | **False.** It runs today. See §1. |
| "Seven places. Nothing else." | **Ten.** All seven are real; the list was incomplete. L8 blocks T2; L9 and L10 defeat the plan's own acceptance test. See §3. |
| "`prepare_run()` is already browser-free" | True about *launching*, false about *importing*. `validate_plan()` pulls in 57 Playwright modules. See L9. |
| T5: "the `<site>_` prefix rule is re-implemented by hand inside each PageModule" | It is also already enforced **centrally**, by a test, with a documented exemption that T5 as drafted would break. See T5. |
| T4: unknown-condition fail-open is a bug to fix | Correct, but it is a *pinned* behaviour — there is a test asserting it. See T4. |
| L1–L7 line numbers | All seven confirmed exact. |
| §2's "already domain-free" table | All ten rows confirmed. |

Everything not listed above survived the audit unchanged.

---

## 1. What "domain-free" means here

Today the engine runs browser steps. The goal is that it runs *steps*, and that
"browser" is one registered domain among several — AWS API calls, HTTP checks,
database assertions — each supplying its own session and its own actions, with
the runner unchanged.

The original draft proposed this as the test of success:

> A workflow of non-browser steps runs to completion, with reporting, retry,
> `when` and `continue_on_failure` all working, and Playwright is never imported.

**That test already passes.** A six-step non-browser workflow was run through
the current `StepRunner` with a plain `object()` in the `page` slot:

```
passed   'set gap'                      passed   'runs when gap>0'
skipped  'skipped when gap>10'          failed   'retries twice'   (2 retries, continue_on_failure)
passed   'after continue_on_failure'    passed   'typo condition'
counts: {'gap': 3}
playwright imported: []
```

Ordering, `when`, retry, `continue_on_failure`, context flow and reporting all
worked. It needed a dummy session object and a **one-method** resolver shim:

```python
class NullResolver:
    def set_context_description(self, description): pass
```

So the honest framing is not "impossible" but **"undignified"**: it works by
accident, through the exception-swallowing in L1 and L2, with no supported seam,
no way for a domain to declare itself, and one undocumented method you must
stub or every step fails (L8).

That is a weaker motivation than the original draft claimed, and still a
sufficient one. The plan below is unchanged in shape — it is about turning an
accident into a contract.

**A revised success test**, since the old one is already green:

> A `noop` domain registered through the ordinary `sites/*/register.py`
> mechanism runs a workflow to completion with no resolver, no hooks and no
> POMs, and `"playwright" not in sys.modules` holds for the whole run —
> including registry construction.

That last clause is what fails today, and L9 is why.

---

## 2. What is already domain-free

This is not a rewrite. Most of the engine is already neutral, by design rather
than by luck. All ten rows re-verified:

| Component | Why it is already fine |
|---|---|
| `StepConfig` | `action` is a string; `extra` is an open dict; no browser type anywhere (`interfaces.py:69-84`) |
| `StepResult` | `status`, `error`, `output`, `duration_ms` — domain-free; `screenshot`/`screenshots` are the web words (`interfaces.py:105-117`) |
| `ExecutionContext` | generic stores; its own docstring already suggests per-domain subclassing (`interfaces.py:144-146`) |
| `ActionRegistry` | a plain `name -> strategy` dict; `create()` knows nothing about what it builds |
| `ActionStrategy.execute` | takes an untyped `page` — nothing in the signature demands Playwright (`interfaces.py:256`) |
| `ReporterStrategy` | `StepRunner` only ever calls the interface |
| `HealerStrategy` | defaults to `None`, gated by `max_heal_attempts > 0`; the cleanest seam in the repo |
| `register_all_sites()` | globs `sites/*/register.py` — would load `sites/aws-account/` with no change (`bootstrap/infra.py:59`) |
| `HumanBehaviour.inter_step_delay()` | pure `asyncio.sleep`; misfiled under `engine/browser/`, but not coupled (`human_behaviour.py:143-152`) |
| `IBrowserLauncher` (used by `ParallelAction`) | the one seam done properly — abstract dependency, concrete type built only at the composition root |

`ParallelAction` is the pattern to copy everywhere else in this plan:
`flow.py:336` takes `browser_launcher=None`, `main.py:259` supplies the concrete
`PlaywrightBrowserLauncher`, and `flow.py:376` fails with a clear message when a
domain that needs one did not get one. That last part — a *legible* failure when
a domain omits an optional dependency — is exactly what L8 does not do.

---

## 3. What leaks — the complete list

Ten places. Seven were in the original draft and all seven are real. Three more
were found by audit, and they are the ones that decide whether this plan lands.

### The original seven

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  L1  step_runner.py:194   _run_step()                              │
  │      await AntiDetection.detect_captcha(self._page)                │
  │      → runs before EVERY step, unconditionally, for every domain   │
  ├────────────────────────────────────────────────────────────────────┤
  │  L2  step_runner.py:226   _run_step()                              │
  │      await self._page.screenshot(path=..., full_page=False)        │
  │      → runs after EVERY step, unconditionally                      │
  ├────────────────────────────────────────────────────────────────────┤
  │  L3  step_runner.py:101   __init__()                               │
  │      resolver: ElementResolver | ShadowRunner                      │
  │      → a TYPED browser dependency in the constructor signature;    │
  │        a non-web domain has no resolver to pass at all             │
  ├────────────────────────────────────────────────────────────────────┤
  │  L4  main.py:561-568      run()                                    │
  │      playwright.start() -> launch_browser() -> open_page()         │
  │      → the only shipped entry point launches a browser BEFORE      │
  │        StepRunner exists                                           │
  ├────────────────────────────────────────────────────────────────────┤
  │  L5  when_eval.py:109,117                                          │
  │      url_contains / element_exists hard-coded in one if/elif       │
  │      → a domain cannot register its own condition vocabulary       │
  ├────────────────────────────────────────────────────────────────────┤
  │  L6  factory.py:35        ActionRegistry.register()                │
  │      self._registry[action.action_name] = action                   │
  │      → NO collision guard. alias() has one (factory.py:89-95);     │
  │        register() silently overwrites.                             │
  ├────────────────────────────────────────────────────────────────────┤
  │  L7  glue_action.py:73    GlueAction._driver()                     │
  │      from poms.shared.driver import PlaywrightDriver               │
  │      return PlaywrightDriver(page)                                 │
  │      → hardcoded construction. This is why ARCHITECTURE.md:388's   │
  │        "Swap the browser adapter -> touches existing code? No"     │
  │        is not accurate today.                                      │
  └────────────────────────────────────────────────────────────────────┘
```

L1 and L2 both swallow exceptions, so a non-browser session does not crash on
them — it silently no-ops. That is incidental fault tolerance, not a seam, and
it is what makes the coupling easy to miss.

### L8 — the one that actually blocks T2

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  L8  step_runner.py:242   _run_retry_loop()                        │
  │      self._resolver.set_context_description(step.description)      │
  │      → unconditional, and INSIDE the retry loop's try block        │
  └────────────────────────────────────────────────────────────────────┘
```

This is the method the shim in §1 had to stub. It is not optional and it is not
guarded. With `resolver=None`, every step fails like this:

```
failed  'NoneType' object has no attribute 'set_context_description'
```

An `AttributeError` laundered into a step failure, then retried `step.retry`
times before the run gives up. The two implementors are
`element_resolver.py:75` and `shadow_runner.py:131` — both web-only.

**T2 as originally drafted does not fix this.** Widening the signature to
`resolver: object | None = None` without guarding line 242 makes the failure
mode worse, not better: silent, per-step, and multiplied by the retry count.
Compare `flow.py:376`, which does this correctly.

### L9 — why T7's acceptance test cannot pass

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  L9  main.py:257          build_action_registry()                  │
  │      from poms.shared.driver import PlaywrightBrowserLauncher      │
  │      → eager import. poms/shared/driver.py:18 is a top-level       │
  │        `from playwright.async_api import Page, ElementHandle`      │
  └────────────────────────────────────────────────────────────────────┘
```

`build_action_registry` is called by `build_validated_registry` (`main.py:315`),
which is called by **both** `prepare_run` and `validate_plan`. Measured:

```python
>>> validate_plan(cfg)                      # main.py:540 — "no browser at all"
>>> "playwright" in sys.modules
True
>>> len([m for m in sys.modules if m.startswith("playwright")])
57
```

So `prepare_run()` is browser-free in the sense that it *launches* nothing, and
not in the sense that matters to T7. `assert "playwright" not in sys.modules`
fails on registry construction alone, before a single step runs.

Note the contrast with `StepRunner` itself, which is clean: importing
`stepper.engine.runner.step_runner` pulls in **zero** Playwright modules. The
leak is in the composition root, not the engine.

### L10 — why T7's test cannot live where the plan implies

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  L10 stepper/tests/conftest.py:7                                   │
  │      from playwright.async_api import async_playwright             │
  │      → top-level. pytest loads ancestor conftests, so this runs    │
  │        for stepper/tests/unit/ too.                                │
  └────────────────────────────────────────────────────────────────────┘
```

Any test placed under `stepper/tests/unit/` has Playwright in `sys.modules`
before its first line executes. The unit suite — whose own docstring says "No
browser, no network" — cannot currently be collected at all without the
`playwright` package installed.

---

## 4. Target shape

```
                  ┌──────────────────────────────────────────┐
                  │   workflow / program  (no domain words)  │
                  │   steps: [ {action, extra, when, retry} ] │
                  └─────────────────────┬────────────────────┘
                                        ▼
        ╔═══════════════════════════════════════════════════════════╗
        ║                        StepRunner                          ║
        ║   order · when · retry · continue_on_failure · observers  ║
        ║   reporters · results                                      ║
        ║                  KNOWS NO DOMAIN AT ALL                    ║
        ╚═══╤════════════════╤═══════════════╤══════════════╤════════╝
            │ session        │ actions       │ hooks        │ conditions
            ▼                ▼               ▼              ▼
   ┌────────────────┐ ┌─────────────┐ ┌────────────┐ ┌────────────────┐
   │ SessionAdapter │ │ActionRegistry│ │  StepHook  │ │ConditionRegistry│
   │ open() close() │ │ name -> impl │ │before/after│ │  name -> eval   │
   └───────┬────────┘ └──────┬──────┘ └─────┬──────┘ └────────┬───────┘
           │                 │              │                 │
  ┌────────┴─────────┬───────┴───────┬──────┴────────┬────────┴──────┐
  ▼                  ▼               ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│   web    │   │   aws    │   │   http   │   │    db    │
│Playwright│   │  boto3   │   │  client  │   │   conn   │
│ +captcha │   │          │   │          │   │          │
│ +screensh│   │ no hooks │   │ no hooks │   │ no hooks │
│ +resolver│   │          │   │          │   │          │
│ +healer  │   │          │   │          │   │          │
│ +POMs    │   │          │   │          │   │          │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
     ▲
     └── every browser-specific thing lives here and nowhere else
```

### A note on the three-layer contract

[`.claude/rules/three-layer-contract.md`](../.claude/rules/three-layer-contract.md)
sets Flow → Glue → POM, with `poms/` importing nothing from `stepper/`. That
rule is web-specific and should stay exactly as it is. A non-web domain has no
POM layer — there are no selectors to protect — so it has two layers, not three:

```
  web domain:     Flow ──► Glue ──► POM ──► Playwright
  aws domain:     Flow ──► Action ─────────► boto3
                            ▲
                            └── no POM layer, because a POM exists to be
                                the single home of CSS selectors, and an
                                API call has none
```

This plan does not touch the POM layer at all.

---

## 5. Three new contracts

Keep them small. Each is one `Protocol`/ABC and one default implementation.

A fourth fell out of T3 and is worth naming here: **`Domain`**
(`stepper/bootstrap/session.py`) is what the composition root asks for the
other three. It is a frozen dataclass of factories — `session`, `hooks`,
`shared` — registered by name, with only `web` registered by default. §5.5
covers it.

### 5.1 `SessionAdapter` — replaces the raw page

```python
class SessionAdapter(Protocol):
    domain: str
    async def open(self) -> object: ...      # returns whatever actions receive
    async def close(self) -> None: ...
```

`WebSession.open()` starts Playwright and returns a `Page`. `AwsSession.open()`
returns a boto3 session. The runner holds the opaque return value and passes it
through, exactly as it passes `page` today — so `ActionStrategy.execute`'s
signature does not change, and all 23 existing engine actions keep working
untouched. (23 verified: `grep -rh "action_name = " stepper/engine/actions/*.py | wc -l`.)

**As landed (T3).** `engine/session.py` carries the contract and `NullSession`
only. The browser's own adapter is `WebSession` in
`stepper/bootstrap/session.py` — bootstrap is the composition-root package, and
keeping the concrete adapter there is what lets the engine stay free of
Playwright. `open()` returns a `Page`, exactly as sketched.

### 5.2 `StepHook` — where the unconditional browser calls go

```python
class StepHook:
    async def before(self, session, step: StepConfig, idx: int) -> StepResult | None: ...
    async def after(self, session, step: StepConfig, result: StepResult, idx: int) -> None: ...
```

`CaptchaHook.before` is L1. `ScreenshotHook.after` is L2. Both registered only
by the web domain. Keep swallowing exceptions *inside* the hooks — that
behaviour is wanted; it just should not be hard-wired into the generic loop.

**As built, two deviations from the sketch above.** Both were forced by what
the code being moved actually does:

- **`idx` is in the signature.** The auto-screenshot filenames are numbered
  from the step index (`step_03_click.png`), so a hook that cannot see the
  index cannot reproduce them. The alternative — a counter inside the hook —
  is stateful and wrong across the sub-runners the heal path builds.
- **`before` returns `StepResult | None`.** L1 does not merely observe; it
  *aborts* the step and substitutes a failure. A hook that can only observe
  could not carry the CAPTCHA gate, so returning a result aborts and returning
  None proceeds.

`StepHook` is a plain base class with both halves defaulting to no-ops, rather
than a Protocol, so a hook that only needs one half writes only one half.

### 5.3 `ConditionRegistry` — replaces the `when_eval` ladder

```python
class ConditionEvaluator(Protocol):
    async def evaluate(self, session, spec, context: ExecutionContext) -> bool: ...
```

Core keeps `all` / `any` / `not` and the context predicates (`context_equals`,
`context_greater_than`, `context_less_than`, `context_between`,
`context_key_exists`). The web domain registers `url_contains` and
`element_exists`. An AWS domain could register `resource_exists` without
touching core.

Fix the fail-open bug while you are in there: `when_eval.py:155-157` returns
`True` for an unknown condition name, so a typo silently runs a step it should
have guarded. With a registry, an unregistered condition should be a plan-time
error, caught by `validate` before any session opens. **See T4 — this is a
pinned behaviour, not an oversight.**

### 5.5 `Domain` — what the composition root asks

```python
@dataclass(frozen=True)
class Domain:
    name: str
    session: Callable[..., SessionAdapter]   # (cfg, settings, test_reporter, *, shared)
    hooks:   Callable[..., list[StepHook]]   # (screenshots_dir)
    shared:  Callable[..., Any]              # (cfg, settings) -> async CM
```

`shared` is the one piece the original plan had no place for, and it is not
invented: `run_data_rows` runs the same workflow once per data row and reuses
**one** browser across all of them. That is an optimisation the web domain
offers, not a property of the session contract — so it sits behind a domain
factory rather than in the runner or in `main.py`. A domain with nothing to
share uses `no_shared`, which yields `None`.

`register_domain` refuses to replace a domain with a *different* one under a
name already taken — the same reasoning as `alias()` in `factory.py`, and the
guard `register()` still lacks (L6, T5). Re-registering the identical `Domain`
is allowed, so a test can swap one in idempotently.

### 5.4 What L8 needs — resolver as an optional dependency

Not a new contract, but the smallest piece of design this plan needs and the
original draft missed. Two options, in preference order:

1. **Null object.** A `NullResolver` with a no-op `set_context_description`,
   defaulted in `StepRunner.__init__` when a domain passes none. One class, no
   call-site changes, and every action that genuinely needs resolution still
   fails at its own point of use with its own message.
2. **Guard the call site.** `if self._resolver is not None:` at `step_runner.py:242`.
   Smaller diff, but it pushes the failure into whichever action dereferences
   the resolver next, as a bare `AttributeError`.

Either way, the outcome T2 must produce is the one `flow.py:376` already
models: a domain that omits an optional dependency and then needs it gets a
sentence explaining that, not an `AttributeError` multiplied by the retry count.

**Settled: option 1.** `stepper/engine/resolvers/null_resolver.py` holds
`NullResolver` and `NoResolverError`. `set_context_description()` is a no-op;
`resolve()` raises and names what was being looked for. It deliberately does
not subclass `ElementResolver` — inheriting would drag the cascade's imports
into a domain that is not paying for them.

---

## 6. Work plan

Eight tickets. T1–T3 are the spine. T4, T5 and T6 can follow in any order.
T7 is new and must land before T8, which is the receipt.

```
  T1 ──► T2 ──► T3 ──► T8          critical path: 4
   │      │      │      ▲
   │      │      └──► T4│
   │      └──► T5       │
   └──► T6              │
        T7 ─────────────┘          T7 is a hard prerequisite for T8
```

### T1 — Extract the per-step browser calls into hooks — **LANDED**

**Files:** `stepper/engine/runner/step_runner.py`, new `stepper/engine/runner/hooks.py`,
new `stepper/tests/unit/test_step_hooks.py`
**Do:** define `StepHook`; move L1 and L2 into `CaptchaHook` / `ScreenshotHook`;
`StepRunner` takes `hooks: list[StepHook] | None = None` and calls them around
`action.execute`.
**Accept:** `pytest stepper/tests/unit/` passes unchanged;
`python stepper/main.py run ol_smoke_test --show` produces the same screenshots
in the same places.
**Risk:** low. Pure move. The screenshot path logic and the "action already
produced one" check (`step_runner.py:222`, `not result.screenshot and not
step.skip_screenshot`) must move together — read them carefully before cutting.

**As landed.** `StepHook`, `CaptchaHook`, `ScreenshotHook` and
`default_web_hooks()` are in `hooks.py`; `StepRunner` takes `hooks=` and falls
back to the web pair when none is given, so every existing caller keeps today's
behaviour and the existing tests pin it unchanged. Hooks propagate into the
sub-runners the heal path builds, so a domain's choice survives healing. A hook
that raises is logged through `log_swallowed` and skipped — a broken hook must
not take the run down.

Two visible changes, neither asserted by any test:

- The abort log line moved from `✗ CAPTCHA wall hit at step 1 — stopping` to
  `✗ Step 1 stopped before it ran — CAPTCHA detected before step …`. The runner
  no longer knows the word CAPTCHA; the hook's own error text carries it, and
  the line is now longer and more specific.
- `step_runner` no longer imports `AntiDetection` at all — `CaptchaHook`
  imports it lazily, inside `before`.

**Verified:** 809 unit tests pass unmodified, plus 16 new ones. A real
Chromium run over navigate / fill / click / assert_text / a missing element
produced all five screenshots with unchanged names and numbering.

### T2 — `SessionAdapter`, and make resolver genuinely optional — **LANDED**

**Files:** `stepper/engine/runner/step_runner.py`, new `stepper/engine/session.py`,
new `stepper/engine/resolvers/null_resolver.py`,
new `stepper/tests/unit/test_domain_free_runner.py`
**Do:** define `SessionAdapter`; change `StepRunner.__init__` to accept `session`
and `resolver: object | None = None` (L3). **And fix L8** — apply §5.4, because
widening the signature without it makes every step fail. Keep the attribute name
`self._page` internally at this stage if it reduces the diff; renaming is T8.
**Accept:** a `StepRunner` constructed with `resolver=None` runs a workflow of
actions that do not use the resolver, and every step reports `passed` — not a
laundered `AttributeError`. An action that *does* need a resolver fails with a
sentence naming the missing dependency.
**Risk:** medium. L8 is the whole ticket; the signature change is the easy half.

**As landed.** `session.py` carries the `SessionAdapter` Protocol and
`NullSession`; the browser's adapter is still built inline in `main.run()`,
which is T3's job. `StepRunner` accepts `session=` as an alias for `page=`
— `page` keeps working and the internal attribute is still `_page`, so the
rename stays T8's. `resolver=` is optional and defaults to `NullResolver`.
The typed `ElementResolver | ShadowRunner` annotation is gone (L3), and with
it the module-level `element_resolver` import.

One signature change worth knowing about: `reporter` and `resolver` swapped
positions, because a parameter cannot take a default while a required one
follows it. Every call site in the tree passes these by keyword, so nothing
broke; a positional caller outside the tree would. `action_factory` and
`reporter` stay mandatory and now raise `TypeError` naming themselves.

**Verified:** a five-step workflow — counters, two `when` branches, an action
that *does* resolve, and `continue_on_failure` — runs against a plain
`object()` session with `resolver` omitted and `hooks=[]`. Steps that do not
resolve pass; the one that does fails with *"This run has no element resolver,
so 'click submit' cannot be resolved…"* rather than an `AttributeError`.

### T3 — Move the browser bootstrap behind the adapter — **LANDED**

**Files:** `stepper/main.py` (`run()`, `open_page()`, `build_pipeline()`,
`run_data_rows()`), new `stepper/bootstrap/session.py`,
new `stepper/tests/unit/test_domains.py`
**Do:** `run()` resolves a `SessionAdapter` by domain and calls `open()`;
`build_pipeline` takes the session, not a Playwright `Browser` (L4).
**Accept:** `python stepper/main.py validate` still launches nothing; `run` on
any existing workflow behaves identically.
**Risk:** medium-high. This is the composition root; `--show`, `--heal`,
anti-detection args and the parallel launcher all pass through here. Do it in
one focused change, not alongside others.

**As landed.** `main.py` no longer names Playwright anywhere. `open_page()` is
gone — its body is `WebSession.open()`. `build_pipeline` takes a session,
opens it, and passes the domain's hooks to the `StepRunner`; the caller owns
closing it. `RunConfig` gained `domain: str = "web"`.

Two things the ticket did not anticipate:

- **`run_data_rows` shares one browser across rows.** A naive "one session per
  run" would have turned one launch into N. Hence `Domain.shared` (§5.5) and
  `WebSession(..., shared=browser)`, which owns the context but not the
  browser. Verified: two rows, one launch.
- **The T1 fallback had to flip here.** `StepRunner` defaulted to the web hook
  pair so T1 could land without breaking callers. Now that the composition
  root supplies them, the default is `[]` — a runner that knows which domain
  it is running is the thing this seam exists to undo. This is a real
  behaviour change for anyone constructing a `StepRunner` directly: **omitting
  `hooks=` used to give you the CAPTCHA gate and auto-screenshots, and now
  gives you neither.** In-tree, `test_step_runner.py`'s fixture is the only
  such caller; it now passes `default_web_hooks(screenshots_dir)` and every
  assertion in that file is unchanged.

**Verified:** 862 unit tests pass, 865 collect across the tree. `validate`
opens nothing. A real Chromium run through `main.run()` — navigate, fill,
click, assert_text — passes 4/4 with one browser launch and screenshots from
the web domain's hook; `run_data_rows` over two rows passes 4/4 twice with
one launch total.

### T4 — Condition registry

**Files:** `stepper/engine/runner/when_eval.py`, web domain registration,
`stepper/tests/unit/test_when_eval.py`
**Do:** registry per §5.3; move `url_contains` / `element_exists` to the web
domain (L5); make an unknown condition a validation error instead of fail-open.
**Accept:** a workflow with a misspelled condition fails `validate` with the bad
name quoted.
**Risk:** low, but it is a behaviour change **with a test pinning the old
behaviour**: `test_when_eval.py:185 test_unknown_condition_fails_open` asserts
exactly what this ticket removes, and its docstring states the intent ("A
typo'd condition key runs the step rather than silently skipping it"). Inverting
it is part of the ticket, not a surprise to discover mid-change. Note the
distinction that test draws against `element_exists`, which fails *closed*
(`when_eval.py:122-126`) — that asymmetry is deliberate and should survive.
Call the change out in the changelog.

### T5 — Namespaced action registry

**Files:** `stepper/engine/actions/factory.py`, `stepper/engine/pages/base_page_module.py`
**Do:** collision guard in `register()` (mirror the one `alias()` already has at
`factory.py:89-95`); enforce the `<site>_` prefix once instead of by hand (L6).

**Re-scoped — read this before starting.** The original draft said the rule is
"re-implemented by hand inside each PageModule.register()" and that the ticket
deletes three hand-copied checks. Both halves need correcting:

- The three checks are all in **openlibrary**
  (`detail_page.py:106`, `login_action.py:99`, `reading_list_action.py:245`).
  SauceDemo and phpTravels never had them. So the rule is applied
  inconsistently, which strengthens the case for centralising it.
- The rule is **already enforced centrally**, by
  `test_page_module_conventions.py::test_every_site_action_is_prefixed_with_its_site`,
  which walks every site's real registration at startup.
- That test carries a documented exemption:
  `_PREFIX_EXEMPT = {"collect_items"}`. `collect_items` is registered unprefixed
  at `search_page.py:77` and then aliased to `ol_collect_books` — the one
  documented exception in the tree, preserved deliberately by
  [`.claude/rules/glue-layer.md`](../.claude/rules/glue-layer.md) and used by the
  shipped `ol_search_and_add.json`.

**A hard prefix check in `register()` therefore breaks `collect_items`.** The
ticket needs an exemption mechanism — a class-level opt-out on the PageModule,
or an explicit `allow_unprefixed=True` on the register call — and the existing
`_PREFIX_EXEMPT` set should become the single source of truth rather than a
second one.
**Accept:** registering two actions with one name raises; the three openlibrary
prefix checks are deleted; `collect_items` still registers and
`ol_search_and_add.json` still runs.
**Risk:** low-medium. May surface an existing duplicate — that is a find, not a
regression.

### T6 — Inject the driver factory

**Files:** `stepper/engine/pages/glue_action.py`
**Do:** `GlueAction` receives a driver factory instead of importing
`PlaywrightDriver` (L7).
**Accept:** `ARCHITECTURE.md:388`'s "Swap the browser adapter → touches existing
code? No" becomes true. Update that table either way — today it is wrong.
**Risk:** low, touches every glue action's construction path. Web-only; no other
domain cares.

### T7 — Make the import graph honest (NEW — prerequisite for T8)

**Files:** `stepper/main.py:257`, `poms/shared/driver.py:18`, `stepper/tests/conftest.py:7`
**Do:** three targeted changes so that "no browser" also means "no Playwright
import":

1. **L9** — make the `PlaywrightBrowserLauncher` construction in
   `build_action_registry` lazy, or move it out of the path
   `validate_plan` takes. Passing a launcher *factory* rather than a launcher
   instance is the smallest change and matches how `browser_launcher` is already
   optional at `factory.py:103`.
2. **L9 (root)** — `poms/shared/driver.py:18` imports `Page` and `ElementHandle`
   at module level for type annotations only. Move them under `TYPE_CHECKING`;
   the file already has `from __future__ import annotations`.
3. **L10** — make `stepper/tests/conftest.py:7` lazy, or move the browser
   fixtures into a conftest that only the integration suite loads. The unit
   suite should be collectable with the `playwright` package absent.

**Accept:** `validate_plan()` completes with `"playwright" not in sys.modules`;
`pytest stepper/tests/unit/` collects and passes in an environment where
`playwright` is not installed.
**Risk:** low, but it touches the POM layer's one shared file — the only ticket
in this plan that does. It changes imports only, no behaviour.

### T8 — The proof: a second domain that does nothing

**Files:** new `stepper/sites/_noop/` (or `examples/noop_domain/`), plus a unit test
**Do:** a noop domain with a `NoopSession` (returns a plain object), two trivial
actions, no hooks, no resolver, no POMs. Add a test that runs a small workflow
of them and asserts `"playwright" not in sys.modules`.
**Accept:** that test passes.

Two constraints the original draft missed:

- **T7 must land first.** Without it the assertion fails on registry
  construction (L9) or on conftest collection (L10), regardless of how clean the
  noop domain is.
- The domain's `register()` must accept the `screenshots_dir` keyword —
  `bootstrap/infra.py:63` calls `mod.register(registry, screenshots_dir=...)` on
  every site it discovers, and a domain that does not take it fails registration
  with the collected-failures error from `infra.py:69`.

**Risk:** none once T7 is in. It is the receipt.

---

## 7. Compatibility guarantees

Non-negotiable; every ticket above is written to preserve these:

1. **No workflow JSON changes.** Every file under `stepper/sites/*/workflows/`
   runs unmodified.
2. **No `ActionStrategy` subclass changes.** All 23 engine actions and every
   glue action keep working with no edit — the first positional argument is
   still "the thing you act on".
3. **No POM layer behaviour changes.** The three-layer contract stands. T7
   touches `poms/shared/driver.py` for imports only.
4. **CLI unchanged.** `list`, `actions`, `validate`, `run`, `--show`, `--heal`,
   `--apply-heals` all behave as documented in
   [`CLAUDE.md`](../CLAUDE.md).
5. **Healing and resolving stay web-only and stay optional**, exactly as they
   are now.

One deliberate exception: **T4 changes `when` semantics** for unknown condition
keys, from fail-open to a validation error. That is the point of the ticket, it
has a test to invert, and it belongs in the changelog.

---

## 8. Non-goals

- Building an AWS (or any real second) domain. T8's noop proves the seam; a real
  domain is a separate decision with its own plan.
- Changing the workflow format, adding a schema, or building an authoring UI.
- Touching the healer, the resolver cascade, or the AI planner.
- Generalising `StepResult.screenshot` / `screenshots` — see §9.

---

## 9. Open questions to settle before T1

1. ~~**Does a domain own a session, or does a workflow?**~~ **Settled in T3:**
   one session per run, and the domain is named on `RunConfig.domain`
   (default `"web"`). A run that wants to share something across several
   sessions — as `run_data_rows` shares a browser — goes through
   `Domain.shared`, not through a longer-lived session. Mixed-domain workflows
   stay out of scope.
2. **`StepResult.screenshot` / `screenshots` are web words on a domain-free
   type** (`interfaces.py:111-112`). Leave them (cheap, harmless) or generalise
   to `artifacts: list[str]` (cleaner, touches every reporter).
   *Recommendation: leave them for now; revisit when a second real domain
   produces artifacts.*
3. **Where does a domain declare itself?** `sites/<name>/register.py` already
   exists and is discovered automatically (`bootstrap/infra.py:59`). Extending
   its `register()` to also return a session factory and hooks is the smallest
   possible change — prefer it over a new registration mechanism. Note its
   current signature takes `screenshots_dir` (see T8).
4. ~~**Null object or call-site guard for L8?**~~ **Settled in T2:** null
   object. See §5.4.

---

## Appendix — how to re-verify

Every claim above is checkable from a clean checkout. The three that matter most:

```bash
# L8 — resolver is not optional today
python - <<'PY'
import asyncio, sys; sys.path.insert(0, ".")
from stepper.engine.interfaces import ActionFactory, ActionStrategy, StepConfig, StepResult
from stepper.engine.runner.step_runner import StepRunner
class A(ActionStrategy):
    action_name = "noop"
    async def _execute(self, page, step, resolver, context, behaviour=None):
        return StepResult(step=step, status="passed")
class F(ActionFactory):
    def create(self, n): return A()
class R:
    def record_step(self, r): pass
runner = StepRunner(page=object(), action_factory=F(), resolver=None,
                    reporter=R(), screenshots_dir=None)
res, _ = asyncio.run(runner.run([StepConfig(action="noop", description="s")]))
print(res[0].status, "|", res[0].error)   # failed | 'NoneType' object has no attribute ...
PY

# L9 — the "no browser at all" path imports Playwright
python -c "
import sys; sys.path.insert(0,'.')
from stepper.main import validate_plan, RunConfig
validate_plan(RunConfig(workflow_path='stepper/sites/saucedemo/workflows/sd_smoke_test.json'))
print('playwright modules:', len([m for m in sys.modules if m.startswith('playwright')]))"

# L10 — the unit suite needs the playwright package
pip uninstall -y playwright && pytest stepper/tests/unit/   # ImportError in conftest.py:7
```

`StepRunner` itself is clean, and it is worth confirming that too — it is the
reason this plan is small:

```bash
python -c "
import sys; sys.path.insert(0,'.')
import stepper.engine.runner.step_runner
print('playwright modules:', [m for m in sys.modules if m.startswith('playwright')])"
# → []
```
