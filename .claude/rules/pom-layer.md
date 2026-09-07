## POM Layer Rules

POMs live in `poms/*/pages/`. They own **selectors and raw page interactions only**.

### The Locator rule

Every interactive element (anything that gets filled or clicked) must be a
`Locator` value object from `poms/shared/locator.py` — never a bare CSS string.
One `Locator` describes one element by every identifier known for it, and it is the
single source of truth for that element.

```python
from poms.shared.locator import Locator

class LoginPage(BasePage):
    class Locators:
        # ── Interactive → must be Locator objects ────────────────────────────
        USERNAME = Locator(
            css="[data-test='username']",
            css_fallbacks=["#user-name"],
            description="username input field",
        )
        SUBMIT = Locator(
            role="button", name="Login",
            css="[data-test='login-button']",
            description="login submit button",
        )

        # ── Read-only state checks → plain CSS is fine ───────────────────────
        ERROR_MSG = "[data-test='error']"
        APP_LOGO  = ".app_logo"
```

**Rule:** fill or click → `Locator` required. `query_selector`, `locator_count`, text
reads → plain CSS string is fine.

### Locator fields

| Field | Kind | Used by |
|---|---|---|
| `role` + `name` | semantic | RoleResolver — `get_by_role` |
| `label` | semantic | LabelResolver — `get_by_label` |
| `placeholder` | semantic | PlaceholderResolver |
| `text` | semantic | TextResolver — `get_by_text` |
| `aria_label` | semantic | metadata |
| `id` | structural | IdResolver |
| `css` | structural | CssResolver — the primary selector |
| `xpath` | structural | XPathResolver |
| `css_fallbacks` | structural | **driver-fallback path only** — not sent to the resolver |
| `description` | metadata | Phase 2 embedding + log messages |

Priority is **not** set per-element. `Locator.to_cfg()` emits a cfg dict and the
resolver cascade applies its own fixed strategy order (see
[resolver-cascade.md](resolver-cascade.md)). Prefer filling in semantic fields —
they survive redesigns; `css`/`xpath` are the fallbacks, not the plan.

Always set `description`: it is what Phase 2 embeds, so a vague one degrades semantic
resolution.

### SharedBasePage — `poms/shared/base_page.py`

`BasePage` there is the canonical base every site's `BasePage` inherits from.
The one method that matters:

```
_interact(locator: Locator, action: str, **kwargs) -> bool
    action="fill"  → kwargs must contain value=str
    action="click" → kwargs may contain js_click=bool
    Returns True on success, False if not found or the action failed. Never raises.
```

`_interact` is the only path interactive elements should take — it dispatches to the
resolver cascade when a resolver is injected and to the driver's CSS candidates when
it is not. There are older `_resolve_and_fill_any` / `_resolve_and_click_any` cfg-list
helpers still present for compatibility; **do not use them in new code.**

### Two operating modes

| Mode | `resolver=` at construction | Behaviour |
|---|---|---|
| driver-only | `None` | `Locator.css_candidates()` tried in order: id → css → css_fallbacks → xpath |
| resolver-enhanced | `ElementResolver` instance | Full cascade via `Locator.to_cfg()`; returns False below `CONFIDENCE_WARN` |

Both modes are live: the glue layer always injects a resolver, and
`examples/plain_pom/` exercises driver-only mode. Neither may be broken.

`behaviour=` is a third optional constructor argument (`HumanBehaviour`). When present,
`_interact` adds jitter before fills and hover-dwell before clicks; when `None`, it acts
immediately. POMs must work with `behaviour=None`.

### What POMs must NOT do

- No flow logic (no loops across pages, no multi-step orchestration)
- No credentials or environment values hardcoded
- No imports from `stepper/` — dependency direction is one-way
- No test assertions — POMs return data, tests assert on it
