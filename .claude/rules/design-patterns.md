## Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| **Strategy** | `ActionStrategy`, `ResolverStrategy`, `ReporterStrategy`, `Planner` | Swap algorithms without changing caller |
| **Template Method** | `ActionStrategy.execute()` | Skeleton in base (`execute`), steps in subclass (`_execute`) |
| **Factory + Registry** | `stepper/engine/actions/factory.py` — `ActionRegistry` | Register actions by name string; create on demand |
| **Observer** | `StepRunner` + `StepObserver` | Decouple reporting/logging from the execution loop |
| **Chain of Responsibility** | `ElementResolver` cascade | Try resolver strategies in priority order; pass on failure |
| **Adapter** | `PlaywrightDriver` wraps Playwright `Page` | Isolate POMs from Playwright API details |
| **Value Object** | `poms/shared/locator.py` — `Locator` | One element, every identifier, two output shapes |
| **Mixin** | `SubStepRunnerMixin` | Sub-step dispatch without a heavyweight base |
| **Dependency Inversion** | `poms/shared/interfaces.py` — `IBrowserDriver`, `IElementHandle` | POMs depend on abstractions, not Playwright concretions |

### Extending the framework

**New action type** → implement `ActionStrategy` (Template Method), register in `ActionRegistry`.

**New resolver strategy** → implement `ResolverStrategy`, add to the chain with a priority value.

**New reporter** → implement `StepObserver`, pass to the `StepRunner` constructor.

**New planner** → implement `Planner`, inject at `StepRunner` construction.

### What the template method actually does

`ActionStrategy.execute()` is small and must not be overridden:

1. defaults `context` to a fresh `ExecutionContext` when the caller passed `None`
2. `await pre_execute(page, step)`
3. `await _execute(page, step, resolver, ctx, behaviour)`
4. `await post_execute(page, step, result)`

**Retry, `continue_on_failure`, healing, observer notification and auto-screenshots are
not here** — they live in `StepRunner` (`_run_step`, `_run_retry_loop`, `_run_heal_loop`).
Do not expect `execute()` to retry anything.

`stepper/tests/unit/test_action_template_method.py` locks this contract: it asserts the
hooks fire, `behaviour` is forwarded, and no subclass defines its own `execute`.

### ActionStrategy skeleton (engine-level actions)

```python
class MyAction(ActionStrategy):
    action_name = "my_action"
    read_only   = True            # True → safe inside ParallelAction

    async def _execute(self, page, step, resolver, context, behaviour=None):
        ...
        return StepResult(step=step, status="passed")
```

### Which status to return

There are five, and only two of them are yours to choose freely. Getting this wrong
is how the engine used to report work it had not done.

| Status | Means | Who returns it |
|---|---|---|
| `passed` | the step did its job | you |
| `failed` | it did not — **including when it could not even try** | you |
| `skipped` | the step was deliberately not run | `StepRunner`, for a false `when:` |
| `healed` | the healer replaced a selector and the retry passed | `StepRunner` only |
| `warned` | nothing produces it; kept in the vocabulary, unused | — |

`skipped` has two other producers, both meaning "no work to do" rather than
"something went wrong": `ol_add_to_shelf` when `context.collected_items` is empty,
and `parallel` with no sub-steps. The second is inconsistent with `scroll_to`, which
**fails** when no element is named — both are a step that cannot run as written. The
difference is that `scroll_to`'s status was incidental and `parallel`'s was chosen
and pinned (`test_no_sub_steps_is_skipped_not_failed`), so it stays until someone
changes it on purpose. If you are adding an action: a malformed step is `failed`.

**A step that did not act returns `failed`.** Not `skipped`, not `warned`. Only
`failed` is read by every consumer that matters:

```python
success_rate = passed / (passed + failed)      # in the report
return 1 if any(r.status == "failed" ...)      # the CLI's exit code
if result.status in ("failed", "skipped"):     # the heal loop's trigger
```

`skipped` is outside the success rate's divisor and outside the exit code, and
`warned` is outside all three. The page primitives returned `skipped` for a
not-found element and `warned` for a below-threshold one, so a click that never
happened produced `success_rate 1.0` and `exit 0` — and, being neither failed nor
skipped, never reached the healer that existed to rescue it. See
`stepper/tests/unit/test_not_found_fails_the_step.py`.

**A dispatcher reports its sub-steps, and declares where they live.**
`_run_sub_steps` returns a list of `StepResult`; if your action drops it and returns
`passed`, every failure inside it disappears. `for_each_item` caught each per-item
exception, took an error screenshot, and then reported the step passed. Continuing
past a failure (`stop_on_failure=False`) is a legitimate choice; reporting it as
success is not.

Set `sub_step_keys` to the `extra` keys you read sub-steps from — `("steps",)` for
`for_each_item` and `parallel`, `("login_steps",)` for `ensure_login`. That is what
`PlanValidator` walks to check nested steps, and it has to be declared rather than
inferred from the key name: `extra` is an open bag and `build_default_registry`
promises a new action needs "zero other changes", so a validator that assumed any
`extra.steps` was executable would reject an action using that name for its own
data. Leave it `()` if your action is not a dispatcher — which is the default, so
there is nothing to do.

Put the class in the `stepper/engine/actions/` module that matches what it does —
`basic.py` (page primitives), `assertions.py` (check or record state), `data.py`
(rows in and out), `flow.py` (dispatches sub-steps), `subflow.py` (runs another
workflow), `measurement.py` (judge the render against a threshold) — re-export it
from `strategies.py`, then register it
in `build_default_registry()` in `stepper/engine/actions/factory.py`.

`strategies.py` is a re-export shim, not a home for classes;
`stepper/tests/unit/test_action_template_method.py` fails if one is defined there.

### GlueAction skeleton (site-specific glue actions)

Site actions subclass `GlueAction`, not `ActionStrategy` directly. `GlueAction` adds
`_build_pom` (enforces resolver + behaviour injection) and `_driver` (wraps the page).

```python
from stepper.engine.pages.glue_action import GlueAction

class MyGlueAction(GlueAction):
    action_name = "my_site_action"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        from poms.mysite.config import load_settings
        from poms.mysite.pages.some_page import SomePage

        settings = load_settings()
        driver   = self._driver(page)
        pom      = self._build_pom(SomePage, driver, settings.base_url,
                                   page=page, resolver=resolver, behaviour=behaviour)
        # call pom methods here
        return StepResult(step=step, status="passed")
```

`behaviour` needs its default: sub-step dispatch may pass `None`.
