---
name: new-site
description: Scaffold a new site — POM layer + glue layer with correct structure, Locator objects, and resolver injection.
argument-hint: "<site-name> <base-url>"
---

Scaffold a new site into the stepper framework.

## Parse $ARGUMENTS

`<site-name>` — e.g. `amazon`, `github` (lowercase, no spaces)
`<base-url>` — e.g. `https://www.amazon.com`

If arguments are missing, ask for them before proceeding.

## What to create

### 1. POM layer — `poms/<site-name>/`

```
poms/<site-name>/
├── config.py          ← Settings dataclass + load_settings() loader
├── data/
│   └── testdata.json  ← Empty JSON object {}
└── pages/
    ├── base_page.py   ← BasePage(SharedBasePage) with delays + open()
    └── login_page.py  ← Example page with Locator objects
```

**base_page.py** must inherit `SharedBasePage` from `poms.shared.base_page`:
```python
from poms.shared.base_page import BasePage as SharedBasePage

class BasePage(SharedBasePage):
    def __init__(self, driver, base_url, delays=None, page=None, resolver=None):
        super().__init__(driver, page=page, resolver=resolver)
        self.base_url = base_url
        self.delays = delays
```

**login_page.py** must use `Locator` objects for all interactive locators:
```python
from poms.shared.locator import Locator

class Locators:
    USERNAME = Locator(
        label="Username", placeholder="Username",
        id="username", css="#username",
        description="username input field",
    )
    PASSWORD = Locator(
        label="Password", css="#password",
        description="password input field",
    )
    SUBMIT = Locator(
        role="button", name="Login", css="[type='submit']",
        description="login submit button",
    )
```

Fill in the semantic fields (`role`/`name`, `label`, `placeholder`) — they survive
redesigns. `css`/`xpath` are fallbacks. There is no per-locator `priority`: strategy
order is fixed by the cascade. Always set `description` — Phase 2 embeds it.

### 2. Glue layer — `stepper/sites/<site-name>/`

```
stepper/sites/<site-name>/
├── pages/
│   └── login_action.py   ← <prefix>_login glue action
└── workflows/
    └── smoke_test.json   ← Minimal smoke workflow
```

**login_action.py** must:
- Pass `page=page, resolver=resolver` to POM constructor
- Register with a `<site-prefix>_login` action name

### 3. After scaffolding

List what was created and remind the user:
- Add credentials to the site's config / env vars (never hardcode)
- Run `/verify-layers` to confirm no contract violations
- Run `/test` after adding tests for the new site
