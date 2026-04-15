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
from engine.pages.glue_action import GlueAction
from poms.<site>.pages.<pom_module> import <PomClass>
from poms.<site>.config import get_settings


class <ActionClass>(GlueAction):
    action_name = "<action-name>"

    async def _execute(self, page, step, resolver, context):
        settings = get_settings()
        driver = self._driver(page)
        pom = self._build_pom(
            <PomClass>, driver, settings.base_url, settings.delays,
            page=page, resolver=resolver          # ← enforced by _build_pom
        )
        # implementation here

    @classmethod
    def register(cls, registry) -> None:
        registry.register(cls())
```

## After creating

1. Register the action: confirm `register()` is called at module import or in site init.
2. Add a usage example step to the relevant workflow JSON.
3. Remind: run `/verify-layers` to confirm the new action doesn't violate the three-layer contract.
