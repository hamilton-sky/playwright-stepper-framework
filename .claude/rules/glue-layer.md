## Glue Layer Rules

Glue files live in `stepper/sites/*/pages/`. Each wraps one POM into a named Stepper
action. **One action, one job.**

### Structure

One `PageModule` subclass per logical page, with the actions as nested `GlueAction`
classes and a `register()` classmethod:

```python
class SDCartPage(PageModule):
    site = "sd"                      # every action_name must start with "sd_"

    class SDViewCartAction(GlueAction):
        action_name = "sd_view_cart"
        read_only   = True           # True → safe inside ParallelAction

        async def _execute(self, page, step, resolver, context, behaviour=None):
            ...

    @classmethod
    def register(cls, registry) -> None:
        registry.register(cls.SDViewCartAction())
```

### `_execute` signature

```python
async def _execute(self, page, step: StepConfig, resolver,
                   context: ExecutionContext,
                   behaviour: HumanBehaviour | None = None) -> StepResult:
```

Five parameters, and `behaviour` **must** have a default — actions are also dispatched
as sub-steps (`for_each_item`, `ensure_login`, `parallel`), where it may be `None`.

Never override `execute()`. It is the template method on `ActionStrategy`: it defaults
the context, runs `pre_execute` / `post_execute`, and forwards `behaviour` into
`_execute`. Overriding it silently disables those hooks —
`stepper/tests/unit/test_action_template_method.py` fails if anyone does.

### Injection contract

Build every POM with `self._build_pom(...)`, never the constructor directly:

```python
# CORRECT
driver     = self._driver(page)
login_page = self._build_pom(LoginPage, driver, settings.base_url,
                             page=page, resolver=resolver, behaviour=behaviour)

# WRONG — resolver cascade never fires, falls back to CSS-only
login_page = LoginPage(driver, settings.base_url)
```

`_build_pom` makes `page`, `resolver` and `behaviour` keyword-mandatory, so forgetting
one is a `TypeError` at the call site rather than a silently degraded run.

### Registration

Actions are registered by **instance**, keyed off `action_name`:

```python
registry.register(cls.MyAction())        # ActionRegistry.register(action) -> self
```

`register()` is fluent, so calls chain. Each site's `stepper/sites/<site>/register.py`
calls `register(registry)` on every PageModule in that site; `main.py` calls that once
at startup.

`action_name` must match the `"action"` key in workflow JSON, and must start with
`f"{site}_"`. The one exception in the tree is `OLSearchPage`, which additionally
aliases `ol_collect_books` to the same instance by assigning into `registry._registry`
directly — a private-dict poke that exists because `ActionRegistry` has no alias API.
Don't copy the pattern; add an alias method if you need a second one.

### Settings loading

Load site settings inside `_execute` via the site's `config.py`, not hardcoded values.
Import lazily inside the method to keep the glue module free of top-level `poms` imports:

```python
from poms.saucedemo.config import load_settings
settings = load_settings()
```

Every site's `config.py` exposes `load_settings()`. (Older docs said `get_settings()`
— no site has ever defined that name.)

### What glue files must NOT do

- No raw Playwright selectors (no `page.locator("#foo")` directly)
- No flow control beyond what a single action needs
- No imports from `stepper/sites/*/workflows/` — flows depend on glue, not the reverse
- Never construct POMs without `page=`, `resolver=` and `behaviour=`
- Never override `execute()`
