---
description: POM layer rules — Locator dataclass, _interact() API, what POMs must not do
globs:
  - "poms/**/*.py"
---

## POM Layer Rules

POMs live in `poms/*/pages/`. They own **selectors and raw page interactions only**.

### The Locator rule

Every interactive element (anything that calls `_interact()`) must be a **`Locator` dataclass instance**. Import it at the top of every POM file:

```python
from poms.shared.locator import Locator
```

```python
class Locators:
    # Interactive elements — MUST be Locator instances
    USERNAME = Locator(
        role="textbox", name="Username",
        label="Username",
        placeholder="Username",
        id="user-name",
        css="[data-test='username']",
        description="username input field",
    )
    SUBMIT = Locator(
        role="button", name="Log in",
        css_fallbacks=["button[type='submit']", ".cta-btn--primary"],
        description="login submit button",
    )

    # Read-only state checks — plain CSS/text strings are fine
    ERROR_MSG = "[data-test='error']"
    APP_LOGO  = ".app_logo"
```

**Rule:** `_interact()` call → `Locator` instance required. `query_selector`, `locator_count`, text reads → plain CSS string is fine.

### Locator fields

| Field | Resolver strategy | Notes |
|---|---|---|
| `role` + `name` | RoleResolver (get_by_role) | Pair together — both or neither |
| `label` | LabelResolver (get_by_label) | |
| `placeholder` | PlaceholderResolver | |
| `text` | TextResolver (get_by_text) | |
| `id` | IdResolver | Omit volatile ids (8+ hex chars or `^[a-z]+-[a-f0-9]{4,}$`) |
| `css` | CssResolver | Primary CSS selector |
| `xpath` | XPathResolver | Last resort |
| `css_fallbacks` | Driver fallback only | Additional CSS tried after `css` fails, in order |
| `description` | Embedding + logs | Plain-English label — always set this |

The resolver cascade tries strategies in the order above. `to_cfg()` converts the instance to the dict the resolver expects.

### SharedBasePage interaction API

`poms/shared/base_page.py` provides the canonical interaction method:

```
SharedBasePage
    └── _interact(locator: Locator, action: str, **kwargs) → bool
          action="fill"  → kwargs must contain value=str
          action="click" → kwargs may contain js_click=bool
```

With `resolver` injected → full 10-stage cascade via `ElementResolver`.
Without `resolver` → driver CSS fallback via `locator.css_candidates()` in order.

Use `_interact()` for all interactive elements — never call the driver directly with a raw CSS string for clicks/fills.

### Two operating modes

| Mode | resolver= at construction | Behaviour |
|---|---|---|
| driver-only | `None` | `Locator.css_candidates()` tried in order via driver |
| resolver-enhanced | `ElementResolver` instance | Full 10-stage cascade; falls back to driver on low confidence |

### What POMs must NOT do

- No flow logic (no loops across pages, no multi-step orchestration)
- No credentials or environment values hardcoded
- No imports from `stepper/sites/` (glue layer) — dependency direction is one-way
- No test assertions — POMs return data, tests assert on it
- No raw CSS/XPath strings passed to `_interact()` — always wrap in `Locator`
