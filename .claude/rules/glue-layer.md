---
description: Glue layer rules — resolver injection contract, _execute signature, action registration
globs:
  - "stepper/sites/**/*.py"
---

## Glue Layer Rules

Glue files live in `stepper/sites/*/pages/`. Each wraps one POM into a named Stepper action. **One action, one job.**

### _execute signature

Every glue action class implements:

```python
def _execute(self, page, step, resolver, context):
    ...
```

`page` and `resolver` are always available here — they must always be forwarded to POM constructors.

### Resolver injection contract

Every POM constructed inside `_execute` **must** receive `page=page, resolver=resolver`:

```python
# CORRECT
login_page = LoginPage(
    driver, settings.base_url, settings.delays,
    page=page, resolver=resolver
)

# WRONG — resolver cascade never fires, falls back to CSS-only
login_page = LoginPage(driver, settings.base_url)
```

This is the most commonly broken pattern. Always verify before submitting.

### Action registration

Every glue file must have a `register()` classmethod that registers the action with the `ActionRegistry`:

```python
@classmethod
def register(cls):
    ActionRegistry.register("my_action_name", cls)
```

The action name used here must match the `"action"` key in workflow JSON steps.

### Settings loading

Load site settings at the top of `_execute` via the site's `config.py`, not hardcoded values:

```python
from poms.openLibrary.config import get_settings
settings = get_settings()
```

### What glue files must NOT do

- No raw Playwright selectors (no `page.locator("#foo")` directly)
- No flow control beyond what's needed for a single action
- No imports from `stepper/sites/*/workflows/` — flows depend on glue, not the reverse
- Never construct POMs without `page=page, resolver=resolver`
