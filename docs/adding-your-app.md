# Pointing Stepper at your own app

The sites in this repo are demos. This is how you add another — yours.

Worth reading first if your app is not reachable from your CI: two of the
sites here run against checked-in fixtures on loopback rather than the live
host, through the base-URL environment variable the site already had. The
pattern is in `stepper/sites/ti/fixtures/` and costs no production code.

Everything below was verified by building a site from scratch against these
steps and running it: `2/2 passed`. If a step here does not work, it is a bug in
this document.

**You will not edit a single existing file.** Discovery is by convention: the
engine globs `stepper/sites/*/register.py` for actions,
`stepper/sites/*/workflows/*.json` for flows, and `poms/*/config.py` for
settings. Adding directories is the whole registration mechanism.

---

> **Adding a non-browser domain instead?** This guide is about pointing Stepper
> at a *web app*: six files, POM layer and glue layer. A domain with no pages —
> a database, an HTTP API, a queue — is a different and smaller shape. It has no
> POMs, because POMs exist to be the single home of CSS selectors and it has
> none, and its actions subclass `ActionStrategy` directly rather than
> `GlueAction`. See `stepper/sites/db/` for a worked example: session,
> preflight, `when` conditions, actions, config and workflows, all declared
> from one folder that no other file references.


## The shape of it

Six files, two directory trees:

```
poms/myApp/                              ← the POM layer: selectors only
├── __init__.py
├── config.py                            ← base_url, credentials, timeouts
└── pages/
    ├── __init__.py
    ├── base_page.py                     ← inherits SharedBasePage
    └── home_page.py                     ← one file per page

stepper/sites/myapp/                     ← the glue layer: named actions
├── __init__.py
├── register.py                          ← the entry point the engine globs for
├── pages/
│   ├── __init__.py
│   └── home_action.py                   ← wraps the POM into "myapp_open_home"
└── workflows/
    └── myapp_smoke.json                 ← the flow
```

### The one naming rule that bites

The POM package and the site directory are matched **case-insensitively**, and
nothing warns you when they disagree by more than case:

| This | must match this |
|---|---|
| `poms/myApp/` | `stepper/sites/myapp/` |
| `poms/openLibrary/` | `stepper/sites/openlibrary/` |

`poms/myApp` ↔ `sites/myapp` resolves. `poms/my_app` ↔ `sites/myapp` does not —
the site loads, the actions register, and `load_settings()` silently falls back
to engine defaults, so your `base_url` is ignored and you get a confusing
navigation failure three steps later.

Every `__init__.py` above is required. A directory of modules without one is
invisible to `find_packages`, so it works from a checkout and vanishes from an
installed copy — `stepper/tests/unit/test_packaging.py` will fail if you forget.

---

## 1. Settings — `poms/myApp/config.py`

Every site exposes `load_settings()`. The shared loader does the
DEFAULTS → `config.yaml` → environment merge; you supply the schema.

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from poms.shared.config import load_config_data

_THIS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    base_url:   str
    username:   str | None
    password:   str | None
    headless:   bool
    slow_mo_ms: int


DEFAULTS: dict = {
    "base_url":   "https://myapp.example.com",
    "username":   None,
    "password":   None,
    "headless":   True,
    "slow_mo_ms": 0,
}

ENV_MAP: dict[str, str] = {
    "MYAPP_BASE_URL": "base_url",
    "MYAPP_USERNAME": "username",
    "MYAPP_PASSWORD": "password",
    "MYAPP_HEADLESS": "headless",
    "MYAPP_SLOW_MO":  "slow_mo_ms",
}


def load_settings(config_path: str | Path | None = None) -> Settings:
    data = load_config_data(
        DEFAULTS, ENV_MAP,
        config_path=config_path if config_path is not None
                    else _THIS_DIR / "config" / "config.yaml",
        bool_fields={"headless"},
        int_fields={"slow_mo_ms"},
    )
    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        username=data.get("username") or None,
        password=data.get("password") or None,
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
    )
```

The `config.yaml` is optional — a missing one is not an error. Credentials
default to `None` on purpose: they belong in `.env` at the repo root, never in
this file. The `Settings` dataclass is deliberately *not* shared between sites;
field sets genuinely differ, and one wide optional-everything class would be
worse than the duplication.

Check it before going further:

```bash
python -c "from poms.myApp.config import load_settings; print(load_settings())"
MYAPP_BASE_URL=https://staging.myapp.test python -c \
  "from poms.myApp.config import load_settings; print(load_settings().base_url)"
```

---

## 2. Base page — `poms/myApp/pages/base_page.py`

Usually this is all of it:

```python
from __future__ import annotations
from poms.shared.base_page import BasePage as SharedBasePage


class BasePage(SharedBasePage):
    """Base for all MyApp page objects."""
```

Worth its own file: site-wide behaviour (a cookie banner every page has to
dismiss, a tenant header) goes here rather than being copy-pasted into each POM.

---

## 3. A page object — `poms/myApp/pages/home_page.py`

POMs own **selectors and raw page interactions, and nothing else**. No flow
logic, no credentials, no assertions — return data and let the caller judge it.

```python
from __future__ import annotations

from poms.myApp.pages.base_page import BasePage
from poms.shared.locator import Locator


class HomePage(BasePage):

    class Locators:
        # Read-only checks — a plain CSS string is fine.
        HEADING    = "h1"
        ERROR_BAR  = ".alert-danger"

        # Anything filled or clicked MUST be a Locator.
        SEARCH = Locator(
            role="searchbox", name="Search",
            placeholder="Search products",
            css="input[name='q']",
            description="the product search box in the site header",
        )
        SUBMIT = Locator(
            role="button", name="Search",
            css="button[type='submit']",
            css_fallbacks=[".search-btn", "#search-submit"],
            description="the search submit button",
        )

    @property
    def url(self) -> str:
        return self.base_url

    async def get_heading(self) -> str | None:
        return await self._get_text_or_none(self.Locators.HEADING)

    async def search_for(self, term: str) -> bool:
        if not await self._interact(self.Locators.SEARCH, "fill", value=term):
            return False
        return await self._interact(self.Locators.SUBMIT, "click")
```

### Filling in a Locator

Fill in **semantic fields first**. `role`+`name`, `label` and `placeholder`
survive redesigns; `css` and `xpath` encode today's markup and break first. The
resolver tries them in that order regardless of what you write first.

`description` is not decoration — it is the string the semantic phase embeds and
the healer matches against. "the product search box in the site header" resolves
when the CSS breaks. "search input" does not.

`css_fallbacks` are for the driver-only path (no resolver injected). The
cascade handles ambiguity itself and never sees them.

`_interact` is the only path interactive elements should take. It returns
`False` rather than raising — check the return value. The older
`_resolve_and_fill_any` / `_resolve_and_click_any` helpers still exist for
compatibility; do not use them in new code.

---

## 4. A glue action — `stepper/sites/myapp/pages/home_action.py`

Glue wraps one POM into one named Stepper action. **One action, one job.**

```python
from __future__ import annotations
import logging

from stepper.engine.browser.human_behaviour import HumanBehaviour
from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class MyAppHomePage(PageModule):
    site = "myapp"                       # every action_name must start with this

    class MyAppSearchAction(GlueAction):
        """Search from the home page and record the term used."""
        action_name = "myapp_search"
        read_only   = False              # True → safe inside a parallel block

        async def _execute(
            self, page, step: StepConfig, resolver,
            context: ExecutionContext,
            behaviour: HumanBehaviour | None = None,
        ) -> StepResult:
            # Imported inside the method, so the glue module stays free of
            # top-level `poms` imports.
            from poms.myApp.config import load_settings
            from poms.myApp.pages.home_page import HomePage

            settings  = load_settings()
            driver    = self._driver(page)
            home_page = self._build_pom(
                HomePage, driver, settings.base_url,
                page=page, resolver=resolver, behaviour=behaviour,
            )

            term = step.extra.get("term") or step.input_value
            if not term:
                return StepResult(step=step, status="failed",
                                  error="myapp_search: no term (extra.term or input_value)")

            await home_page.open()
            if not await home_page.search_for(term):
                return StepResult(step=step, status="failed",
                                  error=f"myapp_search: could not search for {term!r}")

            context.store("last_search", term)
            return StepResult(step=step, status="passed")

    @classmethod
    def register(cls, registry) -> None:
        registry.register(cls.MyAppSearchAction())
```

Four things here are not style preferences:

**Build POMs with `self._build_pom(...)`, never the constructor.** It makes
`page=`, `resolver=` and `behaviour=` keyword-mandatory, so forgetting one is a
`TypeError` at the call site. Call `HomePage(driver, url)` directly and the
resolver cascade never fires — the run silently degrades to CSS-only and looks
fine until a selector changes.

**`behaviour` needs its default.** Actions are also dispatched as sub-steps by
`for_each_item`, `ensure_login` and `parallel`, where it may be `None`.

**Never override `execute()`.** It is the template method: it defaults the
context and runs the pre/post hooks. Override `_execute`.
`stepper/tests/unit/test_action_template_method.py` fails if you override
`execute`.

**The docstring becomes the action's description** in `main.py actions`. Write
it as a whole sentence — there is a test that checks.

---

## 5. Register — `stepper/sites/myapp/register.py`

The file the engine globs for. Imports go inside the function so a broken site
cannot take down the whole registry at import time:

```python
def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.myapp.pages.home_action import MyAppHomePage

    MyAppHomePage.register(registry)
```

That is the entire wiring. No central list to append to.

---

## 6. A workflow — `stepper/sites/myapp/workflows/myapp_smoke.json`

Flows own order, conditions and variables. **No selectors.**

```json
{
  "name": "MyApp — smoke test",
  "description": "search from the home page and confirm results render",
  "variables": { "term": "laptop" },
  "steps": [
    {
      "action": "myapp_search",
      "description": "Search for '{{term}}'",
      "extra": { "term": "{{term}}" }
    },
    {
      "action": "assert_visible",
      "description": "The results list rendered",
      "element": { "css": ".results" },
      "retry": 2
    }
  ]
}
```

Your site's actions and the 23 engine actions (`navigate`, `click`, `fill`,
`assert_visible`, `extract_data`, `for_each_item`, `parallel`, …) are usable
together — `python stepper/main.py actions` lists all of them.

---

## 7. Verify, in this order

Each step fails differently, so run them in order rather than jumping to a run.

```bash
# Is the site discovered at all? Your workflow should appear under "myapp".
python stepper/main.py list

# Did the actions register? Missing here = register.py was not found or raised.
python stepper/main.py actions --site myapp

# Does the JSON reference only registered actions? No browser needed.
python stepper/main.py validate

# Run it, with a visible browser.
python stepper/main.py run myapp_smoke --show

# Watch the resolution cascade decide.
python stepper/main.py run myapp_smoke --show 2>&1 | grep -E "✓|✗|confidence"
```

A first real run prints lines like:

```
✓ Step 1 → passed
✓ [css] found 1 element — confidence 75%
✓ assert_visible: element is visible
  Result: 2/2 passed  (0 failed)
```

`confidence 75%` means it matched on CSS — the least durable identifier. Add
`role`/`name` or `label` to that Locator and it will climb to 93-95%.

---

## When it does not work

| Symptom | Cause |
|---|---|
| Site missing from `list` | No `workflows/*.json`, or the directory is not under `stepper/sites/` |
| Actions missing from `actions --site` | `register.py` absent, or it raised — run `python -c "from stepper.sites.myapp.register import register"` to see the error |
| `Unknown action: 'myapp_x'` | `action_name` and the JSON `"action"` disagree, or `register()` was never called on that PageModule |
| Settings ignored, wrong `base_url` | `poms/<name>` and `sites/<name>` differ by more than case |
| `TypeError: _build_pom() missing keyword` | Good — that is the injection contract. Pass `page=`, `resolver=`, `behaviour=` |
| Everything resolves at 75% | Locators have only `css`. Add semantic fields |
| Works locally, `ImportError` when installed | A missing `__init__.py` — `pytest stepper/tests/unit/test_packaging.py` names it |
| `read_only` action mutates state inside `parallel` | `read_only = True` is a promise the engine trusts. Only set it for actions that genuinely read |

---

## Before you commit

```bash
pytest stepper/tests/unit/        # ~500 tests, ~4s, no browser or credentials
python stepper/main.py validate   # exits 1 if any workflow is invalid
```

Both run with no network and no keys, so there is no reason not to.

---

## Further reading

| Topic | Where |
|---|---|
| Locator fields and the two operating modes | [.claude/rules/pom-layer.md](../.claude/rules/pom-layer.md) |
| Injection contract, registration, aliases | [.claude/rules/glue-layer.md](../.claude/rules/glue-layer.md) |
| Layer boundaries and the anti-pattern table | [.claude/rules/three-layer-contract.md](../.claude/rules/three-layer-contract.md) |
| Resolution cascade and confidence constants | [.claude/rules/resolver-cascade.md](../.claude/rules/resolver-cascade.md) |
| Failure modes the POMs guard against | [playwright-pitfalls.md](playwright-pitfalls.md) |
| Driving POMs with no engine at all | [`examples/plain_pom/`](../examples/plain_pom/) |
