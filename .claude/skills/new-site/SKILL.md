---
name: new-site
description: Scaffold a new site — POM layer + glue layer with correct structure, cfg lists, and resolver injection.
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
├── config.py          ← Settings dataclass + get_settings() loader
├── data/
│   └── testdata.json  ← Empty JSON object {}
└── pages/
    ├── base_page.py   ← BasePage(SharedBasePage) with delays + open()
    └── login_page.py  ← Example page with cfg list locators
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

**login_page.py** must use cfg lists for all interactive locators:
```python
class Locators:
    USERNAME_CFG = [
        {"label": "Username", "priority": 10},
        {"placeholder": "Username", "priority": 20},
        {"id": "username", "priority": 30},
        {"css": "#username", "priority": 40},
    ]
    PASSWORD_CFG = [
        {"label": "Password", "priority": 10},
        {"css": "#password", "priority": 20},
    ]
    SUBMIT_CFG = [
        {"role": "button", "name": "Login", "priority": 10},
        {"css": "[type='submit']", "priority": 20},
    ]
```

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
