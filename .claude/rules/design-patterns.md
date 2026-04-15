---
description: Design patterns used in the stepper framework and where to find them
globs:
  - "stepper/engine/**/*.py"
  - "stepper/sites/**/*.py"
  - "poms/shared/**/*.py"
---

## Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| **Strategy** | `ActionStrategy`, `ResolverStrategy`, `Reporter`, `Planner` | Swap algorithms without changing caller |
| **Template Method** | `ActionStrategy.execute()` | Skeleton in base (`execute`), steps in subclass (`_execute`) |
| **Factory + Registry** | `stepper/engine/actions/factory.py` — `ActionRegistry` | Register actions by name string; create on demand |
| **Observer** | `StepRunner` + `StepObserver` | Decouple reporting/logging from execution loop |
| **Chain of Responsibility** | `ElementResolver` cascade | Try resolver strategies in priority order; pass on failure |
| **Adapter** | `PlaywrightDriver` wraps Playwright `Page` | Isolate POMs from Playwright API details |
| **Dependency Inversion** | `poms/shared/interfaces.py` — `IBrowserDriver`, `IElementHandle` | POMs depend on abstractions, not Playwright concretions |

### Extending the framework

**New action type** → implement `ActionStrategy` (Template Method), register in `ActionRegistry`.

**New resolver strategy** → implement `ResolverStrategy` interface, add to resolver chain with a priority value.

**New reporter** → implement `StepObserver`, pass to `StepRunner` constructor.

**New planner** → implement `Planner` interface, inject at `StepRunner` construction.

### ActionStrategy skeleton (engine-level actions)

```python
class MyAction(ActionStrategy):
    action_name = "my_action"

    async def _execute(self, page, step, resolver, context):
        # your logic here
        pass
```

`execute()` in the base class handles retry, observer notification, and error wrapping.
`_execute()` is your implementation slot — keep it focused on one job.

### GlueAction skeleton (site-specific glue actions)

All site actions must subclass `GlueAction` (not `ActionStrategy` directly).
`GlueAction` enforces resolver injection via `_build_pom` and wraps the driver via `_driver`.

```python
from engine.pages.glue_action import GlueAction

class MyGlueAction(GlueAction):
    action_name = "my_site_action"

    async def _execute(self, page, step, resolver, context):
        from poms.mysite.config import get_settings
        from poms.mysite.pages.some_page import SomePage
        settings = get_settings()
        driver = self._driver(page)
        pom = self._build_pom(SomePage, driver, settings.base_url,
                              page=page, resolver=resolver)
        # call pom methods here
```
