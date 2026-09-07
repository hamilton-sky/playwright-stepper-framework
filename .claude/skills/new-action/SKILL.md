---
name: new-action
description: Add a new glue action to an existing site, wired correctly with resolver injection.
argument-hint: "<site-name> <action-name> [<pom-page>]"
---

Add a new glue action to an existing site.

## Parse $ARGUMENTS

- `<site-name>` — e.g. `openlibrary`, `saucedemo`
- `<action-name>` — e.g. `ol_remove_book`, `sd_apply_filter`
- `<pom-page>` — optional, the POM class to use (e.g. `BookDetailPage`)

If arguments are missing, ask before proceeding.

## Pre-flight

1. Verify `stepper/sites/<site-name>/pages/` exists.
2. Verify the referenced POM exists in `poms/<site>/pages/`.
3. Check `stepper/engine/actions/factory.py` to understand how registration works.

## What to create

Create `stepper/sites/<site-name>/pages/<action_name>_action.py`:

```python
from engine.browser.human_behaviour import HumanBehaviour
from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.glue_action import GlueAction


class <ActionClass>(GlueAction):
    action_name = "<site-prefix>_<action-name>"     # must start with the site prefix
    read_only   = False                             # True → safe inside ParallelAction

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext,
                       behaviour: HumanBehaviour | None = None) -> StepResult:
        # Import POMs lazily so the glue module has no top-level poms dependency.
        from poms.<site>.config import load_settings
        from poms.<site>.pages.<pom_module> import <PomClass>

        settings = load_settings()
        driver   = self._driver(page)
        pom      = self._build_pom(
            <PomClass>, driver, settings.base_url, settings.delays,
            page=page, resolver=resolver, behaviour=behaviour,   # ← enforced by _build_pom
        )
        # implementation here
        return StepResult(step=step, status="passed")

    @classmethod
    def register(cls, registry) -> None:
        registry.register(cls())
```

## After creating

1. Register the action: confirm the PageModule's `register()` is reached from
   `stepper/sites/<site>/register.py`, which `main.py` calls once at startup.
2. Add a usage example step to the relevant workflow JSON.
3. Remind: run `/verify-layers` to confirm the new action doesn't violate the three-layer contract.
