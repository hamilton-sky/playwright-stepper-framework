---
description: POM layer rules — locator cfg lists, SharedBasePage API, what POMs must not do
globs:
  - "poms/**/*.py"
---

## POM Layer Rules

POMs live in `poms/*/pages/`. They own **selectors and raw page interactions only**.

### The cfg list rule

Every interactive element (anything that calls `fill()` or `click()`) must be a **prioritised list of dicts**. This is the single source of truth — no parallel plain strings.

```python
class Locators:
    # Interactive inputs — MUST be cfg lists
    USERNAME_CFG = [
        {"label":       "Username",       "priority": 10},
        {"placeholder": "Username",       "priority": 20},
        {"id":          "username",       "priority": 30},
        {"css":         "#username",      "priority": 40},
    ]
    SUBMIT_CFG = [
        {"role": "button", "name": "Log in",  "priority": 10},
        {"role": "button", "name": "Sign in", "priority": 20},
        {"css":  ".cta-btn--primary",         "priority": 30},
    ]

    # Read-only state checks — plain CSS/text strings are fine
    ERROR_MSG = "[data-test='error']"
    APP_LOGO  = ".app_logo"
```

**Rule:** `fill()` or `click()` call → cfg list required. `query_selector`, `locator_count`, text reads → plain CSS is fine.

### cfg dict keys

| Key | Resolver strategy | Priority (default) |
|---|---|---|
| `role` + `name` | RoleResolver (get_by_role) | 10 |
| `label` | LabelResolver (get_by_label) | 20 |
| `placeholder` | PlaceholderResolver | 30 |
| `text` | TextResolver (get_by_text) | 40 |
| `id` | IdResolver | 50 |
| `css` | CssResolver | 60 |
| `xpath` | XPathResolver | 70 |

Always set explicit `"priority"` values — lower = tried first.

### SharedBasePage helper methods

`poms/shared/base_page.py` provides all resolver-aware helpers. Every site BasePage inherits from it.

```
SharedBasePage
    ├── _ordered_cfgs(cfgs)              → sorted by priority
    ├── _resolve_and_fill(cfg, value)    → single cfg → fill
    ├── _resolve_and_click(cfg)          → single cfg → click
    ├── _resolve_and_fill_any(cfgs, v)   → try list in priority order → fill first match
    └── _resolve_and_click_any(cfgs)     → try list in priority order → click first match
```

Use `_resolve_and_fill_any` / `_resolve_and_click_any` for interactive elements — never call driver directly with a raw CSS string for clicks/fills.

### Two operating modes

| Mode | resolver= at construction | Behaviour |
|---|---|---|
| driver-only | `None` | CSS/id extracted from cfg dict, called via driver |
| resolver-enhanced | `ElementResolver` instance | Full 10-stage cascade; falls back to driver on low confidence |

### What POMs must NOT do

- No flow logic (no loops across pages, no multi-step orchestration)
- No credentials or environment values hardcoded
- No imports from `stepper/sites/` (glue layer) — dependency direction is one-way
- No test assertions — POMs return data, tests assert on it
