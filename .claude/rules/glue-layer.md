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

### A step that did not act must not report "passed"

POM methods return whether they acted (see
[pom-layer.md](pom-layer.md)). The glue is where that becomes a step status:

```python
if not await login_page.fill_username(username):
    return StepResult(
        step=step, status="failed",
        error="sd_login: fill_username() did not act — the selector matched "
              "nothing, or the element was present but not interactable",
    )
```

Name the action and the method that missed. A run log then points at the step
rather than at the framework — the difference between *"the Click Here link was
not clicked"* and *"Timeout 30000ms exceeded while waiting for event page"*.

Every site in this tree once returned `passed` unconditionally, and it hid real
defects: a Pathly smoke test reported ten passed steps against an app whose
wizard never opened, `ti_hover_user` reported green on a selector matching zero
elements, and `ti`'s login flow reported 2/2 on a **wrong password**.

An action whose job is to *report* a fact has the same duty from the other
side: `if flash:` made "no flash" indistinguishable from "flash", and
`extra.get("expected_names", [])` made an assertion pass vacuously when the key
was misspelled. Validate the input, fail on the absent fact.

`pt_book_hotel` is the version of this to watch for. Every interaction landed —
the fields filled, the button clicked, `submit_booking()` returned `True` — and
the page came back without a booking. It logged a warning and returned `passed`.
A click that lands is not the fact; the fact is what the page shows afterwards,
and a step named for it has to read that and fail when it is absent.

The engine-level reporting actions had the same hole, and there it needs no
broken page at all: `assert_text` defaulted `extra.expected` to `""` (inside
every string there is, under `contains`) and `assert_count` defaulted both sides
of its comparison to `0`. Both now fail as configuration errors, while an
explicit `""` or `0` stays a real expectation — see
`stepper/engine/actions/assertions.py` and
`stepper/tests/unit/test_assertion_input_validation.py`.

`stepper/tests/unit/test_failure_propagation.py` fails the build on both
halves. If ignoring a result really is deliberate, assign it (`_ = await ...`)
so the choice is visible.

### What glue files must NOT do

- No raw Playwright selectors (no `page.locator("#foo")` directly)
- No importing `PlaywrightDriver` yourself — `self._driver(page)` builds whatever
  adapter the run is configured with (`set_driver_factory` in `glue_action.py`)
- No flow control beyond what a single action needs
- No imports from `stepper/sites/*/workflows/` — flows depend on glue, not the reverse
- Never construct POMs without `page=`, `resolver=` and `behaviour=`
- Never override `execute()`
