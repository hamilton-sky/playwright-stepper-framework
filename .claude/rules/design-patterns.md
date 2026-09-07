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

Register it in `build_default_registry()` in `stepper/engine/actions/factory.py`.

### GlueAction skeleton (site-specific glue actions)

Site actions subclass `GlueAction`, not `ActionStrategy` directly. `GlueAction` adds
`_build_pom` (enforces resolver + behaviour injection) and `_driver` (wraps the page).

```python
from engine.pages.glue_action import GlueAction

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
