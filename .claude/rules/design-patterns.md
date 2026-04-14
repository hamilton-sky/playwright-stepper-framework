---
description: Design patterns used in the stepper framework and where to find them
globs:
  - "stepper/stepper/**/*.py"
  - "poms/shared/**/*.py"
---

## Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| **Strategy** | `ActionStrategy`, `ResolverStrategy`, `Reporter`, `Planner` | Swap algorithms without changing caller |
| **Template Method** | `ActionStrategy.execute()` | Skeleton in base (`execute`), steps in subclass (`_execute`) |
| **Factory + Registry** | `stepper/stepper/actions/factory.py` — `ActionRegistry` | Register actions by name string; create on demand |
| **Observer** | `StepRunner` + `StepObserver` | Decouple reporting/logging from execution loop |
| **Chain of Responsibility** | `ElementResolver` cascade | Try resolver strategies in priority order; pass on failure |
| **Adapter** | `PlaywrightDriver` wraps Playwright `Page` | Isolate POMs from Playwright API details |
| **Dependency Inversion** | `poms/shared/interfaces.py` — `IBrowserDriver`, `IElementHandle` | POMs depend on abstractions, not Playwright concretions |

### Extending the framework

**New action type** → implement `ActionStrategy` (Template Method), register in `ActionRegistry`.

**New resolver strategy** → implement `ResolverStrategy` interface, add to resolver chain with a priority value.

**New reporter** → implement `StepObserver`, pass to `StepRunner` constructor.

**New planner** → implement `Planner` interface, inject at `StepRunner` construction.

### ActionStrategy skeleton

```python
class MyAction(ActionStrategy):
    def _execute(self, page, step, resolver, context):
        # your logic here
        pass

    @classmethod
    def register(cls):
        ActionRegistry.register("my_action", cls)
```

`execute()` in the base class handles retry, observer notification, and error wrapping.
`_execute()` is your implementation slot — keep it focused on one job.
