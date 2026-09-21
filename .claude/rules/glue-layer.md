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

Actions are registered by **instance**, through `PageModule.register_actions()`:

```python
@classmethod
def register(cls, registry) -> None:
    cls.register_actions(registry, cls.MyAction(), cls.MyOtherAction())
```

`register_actions` checks the naming rule once and then registers. Use it rather
than `registry.register()` directly — the check used to be hand-copied into three
of OpenLibrary's register() methods and missing from the other ten.

Each site's `stepper/sites/<site>/register.py` calls `register(registry)` on every
PageModule in that site; `main.py` calls that once at startup.

`action_name` must match the `"action"` key in workflow JSON, and must start with
`f"{site}_"`. `ActionRegistry.register()` also refuses a name another action
already holds — one flat namespace across every site means a collision would
otherwise just overwrite, and the only symptom is a workflow running the wrong
site's action.

The one exception in the tree is `OLSearchPage`, whose action is registered as
`collect_items` and additionally aliased to `ol_collect_books`. A deliberate
exception is declared on the class, so the rule and its hole live together:

```python
class OLSearchPage(PageModule):
    site = "ol"
    unprefixed_actions = frozenset({"collect_items"})   # predates the convention

    @classmethod
    def register(cls, registry) -> None:
        action, = cls.register_actions(registry, cls.OLCollectBooksAction())
        registry.alias("ol_collect_books", action.action_name)
```

`alias()` binds a second name to the *same instance*, and refuses to point at an
unregistered action or to shadow a different one. Prefer a single name; reach for
an alias only to keep an existing workflow working after a rename.

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
- No importing `PlaywrightDriver` yourself — `self._driver(page)` builds whatever
  adapter the run is configured with (`set_driver_factory` in `glue_action.py`)
- No flow control beyond what a single action needs
- No imports from `stepper/sites/*/workflows/` — flows depend on glue, not the reverse
- Never construct POMs without `page=`, `resolver=` and `behaviour=`
- Never override `execute()`
