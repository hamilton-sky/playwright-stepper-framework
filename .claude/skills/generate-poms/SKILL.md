---
name: generate-poms
description: Read .stepper/trace.json and generate a complete three-layer site implementation (POMs, glue, workflows, config) under poms/<site>/ and stepper/sites/<site>/.
argument-hint: "[--input <trace.json path>] [--site <site_short_name>]"
---

You are generating a complete three-layer site implementation from a discovery trace. Work through the sections below in order. After every Write or Edit, read the tool result for `VIOLATION:` or `ERROR:` markers and self-correct before writing the next file.

## Parse Arguments

Parse `$ARGUMENTS`:
- `--input` — path to the trace file. Default: `.stepper/trace.json`
- `--site` — short name for the new site (e.g. `sd`, `ol`, `pt`). **Required.**
- `--force` — if present, overwrite existing site directories

If `--site` is missing, stop immediately with: `Error: specify --site short_code (e.g. --site sd)`

Load the trace file. If it does not exist, stop with: `Error: trace file not found — run /discover-site first`

Parse the JSON. If `pages` is empty or missing, stop with: `Error: trace is empty — no pages to generate from`

If `poms/<site>/` already exists and `--force` is not set, stop with:
```
Error: site already exists:
  poms/<site>/
  stepper/sites/<site>/
Pass --force to overwrite.
```

---

## Site Scaffold

Generate the following files **before** any POM files. Reference `poms/saucedemo/config.py` and `poms/saucedemo/pages/base_page.py` as canonical patterns.

### Files to create

**`poms/<site>/__init__.py`** — empty file.

**`poms/<site>/config.py`** — settings loader. Follow this exact shape (adapt env prefix and defaults to the new site):

```python
"""<site>/config.py — Settings loader."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os

try:
    import yaml
except Exception:
    yaml = None

_THIS_DIR = Path(__file__).resolve().parent

@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str | None
    password: str | None

DEFAULTS: dict = {
    "base_url": "<base_url from trace>",
}

ENV_PREFIX = "<SITE_UPPER>"  # e.g. SD, OL, PT

ENV_MAP: dict[str, str] = {
    f"{ENV_PREFIX}_BASE_URL":  "base_url",
    f"{ENV_PREFIX}_USERNAME":  "username",
    f"{ENV_PREFIX}_PASSWORD":  "password",
}

def load_settings(config_path=None) -> Settings:
    if config_path is None:
        config_path = _THIS_DIR / "config" / "config.yaml"
    data = dict(DEFAULTS)
    path = Path(config_path)
    if path.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config.yaml")
        file_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(file_data, dict):
            data.update(file_data)
    for env_key, field in ENV_MAP.items():
        if env_key in os.environ:
            data[field] = os.environ[env_key]
    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        username=data.get("username") or None,
        password=data.get("password") or None,
    )
```

Set `base_url` in DEFAULTS from `trace.pages[0].url` (strip path — keep scheme + hostname only).

**`poms/<site>/config/config.yaml`** — placeholder:
```yaml
base_url: "<base_url from trace>"
# username: ""
# password: ""
```

**`poms/<site>/pages/__init__.py`** — empty file.

**`poms/<site>/pages/base_page.py`** — extension point:
```python
"""<site>/pages/base_page.py — Base class for all <Site> pure POMs."""
from __future__ import annotations
import logging
from poms.shared.base_page import BasePage as SharedBasePage

logger = logging.getLogger(__name__)

class BasePage(SharedBasePage):
    """Base for all <Site> page objects."""
```

**`stepper/sites/<site>/__init__.py`** — empty file.

**`stepper/sites/<site>/pages/__init__.py`** — empty file.

**`stepper/sites/<site>/workflows/`** — create the directory (write a `.gitkeep` placeholder if needed).

---

## POM Generation

For each entry in `trace.pages`, generate one POM file.

### Naming

- Module name: take `page.slug`, convert to snake_case, append `_page` → `poms/<site>/pages/<slug>_page.py`
- Class name: PascalCase of slug + `Page` → e.g. `login` → `LoginPage`

### Locators class

Build a `Locators` inner class. For each element in `page.elements` where the element is interactive (role in `button`, `link`, `checkbox`, `combobox`, `textbox`, `searchbox`; or tag in `input`, `select`, `textarea`, `button`):

1. Derive a Python identifier from `element.name` or `element.label` or `element.placeholder` — lowercased, spaces replaced with `_`, non-alphanum stripped.

2. Create a `Locator` instance named `<IDENTIFIER>`. Populate fields from the trace element — include only non-empty values:
   - `role`, `name` — from element `role` and `name`
   - `label` — from element `label`
   - `placeholder` — from element `placeholder`
   - `id` — from element `id` (omit if volatile: matches `[a-z0-9]{8,}` pure hex or `^[a-z]+-[a-f0-9]{4,}$`)
   - `css` — from element `css`
   - `description` — plain-English label: `"<name> <role>"` (e.g. `"username input field"`)

3. If an element has no selector keys at all, write:
   ```python
   # TODO: trace lacked all selectors for this element
   <IDENTIFIER> = Locator(description="<name> — no selectors in trace")
   ```

The `Locator` dataclass lives in `poms.shared.locator`. Import it at the top of every POM file:
```python
from poms.shared.locator import Locator
```

Example Locators class:
```python
from poms.shared.locator import Locator

class Locators:
    USERNAME = Locator(
        role="textbox", name="Username",
        label="Username",
        placeholder="Username",
        id="user-name",
        css="[data-test='username']",
        description="username input field",
    )
    LOGIN_BUTTON = Locator(
        role="button", name="Login",
        css="[data-test='login-button']",
        description="login submit button",
    )
    # Read-only state checks — plain CSS string, no Locator needed
    ERROR_MSG = "[data-test='error']"
```

**Rule:** every interactive element gets a `Locator` instance. Plain CSS strings are only for read-only state checks (`query_selector`, text reads). Never use a raw string as the argument to `_interact()`.

### Methods

For each interactive element, call `_interact()` with the `Locator` instance:
- If textbox / textarea / searchbox: `async def fill_<identifier>(self, value: str) -> None` calling `await self._interact(self.Locators.<IDENTIFIER>, "fill", value=value)`
- If button / link / checkbox / combobox / select: `async def click_<identifier>(self) -> None` calling `await self._interact(self.Locators.<IDENTIFIER>, "click")`

### url property

```python
@property
def url(self) -> str:
    return f"{self.base_url}<path_suffix>"  # path_suffix derived from page.url
```

### wait_for_ready

Use the first interactive element's `css` field directly:

```python
async def wait_for_ready(self) -> None:
    try:
        await self._driver.wait_for_selector(
            self.Locators.<FIRST_INTERACTIVE>.css, timeout=15_000
        )
    except Exception:
        pass
```

If the first element has no `css`, use its `id` as `f"#{self.Locators.<FIRST_INTERACTIVE>.id}"`.

### Full generated POM file shape

```python
"""<site>/pages/<slug>_page.py — Pure POM for <Title> page."""
from __future__ import annotations
import logging
from poms.<site>.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class <PageClass>(BasePage):

    class Locators:
        <IDENTIFIER> = Locator(
            role="...", name="...",
            css="...",
            description="...",
        )
        ...

    @property
    def url(self) -> str:
        return f"{self.base_url}/<path>"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.<FIRST>.css, timeout=15_000
            )
        except Exception:
            pass

    async def fill_<name>(self, value: str) -> None:
        await self._interact(self.Locators.<NAME>, "fill", value=value)

    async def click_<name>(self) -> None:
        await self._interact(self.Locators.<NAME>, "click")
```

### After each POM Write

Read the tool result. If it contains `VIOLATION:` or `ERROR:`:
- `"raw string passed to _interact"` or `"interactive locator not a Locator instance"` → replace the plain string with a `Locator(css="...", description="...")` instance
- Any other violation → apply the minimal fix described in the message
- Re-Edit the file before writing the next POM
- If the hook output appears to be a false positive (same code passes on second attempt), log a one-line justification and continue

---

## Glue Generation

For each logical cluster of related actions derived from the trace (e.g. login, search, navigate, checkout), generate one glue file.

### Naming

- File: `stepper/sites/<site>/pages/<action_group>.py` (e.g. `login_action.py`, `search_action.py`)
- Outer class: `<Site><Page>Page(PageModule)` — e.g. `GenSdLoginPage`
- site attribute: `site = "<site>"`
- Inner action class: `<Site><Action>(GlueAction)` — e.g. `GenSdLoginAction`
- `action_name`: `"<site>_<action>"` — e.g. `"gen_sd_login"`

### Canonical glue file shape

Reference `stepper/sites/saucedemo/pages/login_action.py` as the canonical pattern. Every generated glue file must follow this exact structure:

```python
"""sites/<site>/pages/<action_group>.py — Stepper glue for <Site> <action>."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class <Site><Page>Page(PageModule):
    site = "<site>"

    class <Site><Action>Action(GlueAction):
        action_name = "<site>_<action>"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.<site>.config import load_settings
                from poms.<site>.pages.<slug>_page import <PageClass>

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(<PageClass>, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                # call POM methods in logical order
                # e.g. await pom.fill_username(step.extra.get("username") or settings.username)

                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("<site>_<action> failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.<Site><Action>Action()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
```

### Resolver injection contract (mandatory)

Every `_build_pom` call **must** include `page=page, resolver=resolver`. Missing either disables the entire resolution cascade. This is the most commonly broken pattern — verify every generated glue file before moving on.

```python
# CORRECT
pom = self._build_pom(LoginPage, driver, settings.base_url,
                      page=page, resolver=resolver, behaviour=behaviour)

# WRONG — never do this
pom = self._build_pom(LoginPage, driver, settings.base_url)
```

### What glue files must NOT do

- No `page.locator()`, `page.get_by_role()`, `page.get_by_label()`, or any raw Playwright selector calls
- No CSS / XPath strings hardcoded in glue — all selectors live in POM Locators cfg lists
- No imports from other `stepper/sites/` directories
- No flow control beyond what is needed for a single atomic action

### After each glue Write

Read the tool result. If it contains `VIOLATION:` or `ERROR:`:
- `"missing resolver injection"` → add `page=page, resolver=resolver` to the `_build_pom` call
- `"raw page.locator in glue"` → move the selector into the POM's Locators class as a cfg list entry, expose a method, call that method from glue
- `"wrong import direction"` → remove the import from `stepper/sites/`; glue imports from `poms/` only
- Re-Edit the file to fix the violation before writing the next file

---

## Workflow Generation

After all POM and glue files are written, generate one workflow JSON file.

### File location

`stepper/sites/<site>/workflows/<flow_name>.json`

- `flow_name`: use the `flow` field from `trace.json` if present; otherwise default to `<site>_smoke_test`

### JSON schema

Reference `stepper/sites/saucedemo/workflows/sd_smoke_test.json` as the canonical shape:

```json
{
  "name": "<Site> — <flow description>",
  "description": "<one sentence describing the workflow>",
  "continue_on_failure": true,
  "steps": [
    {
      "action": "<site>_<action>",
      "description": "<human-readable description of this step>"
    }
  ]
}
```

### Rules

- One step per generated `GlueAction`, in the same order they appear in the trace
- `action` value must exactly match the `action_name` defined in the corresponding glue file
- **No CSS selectors, XPath expressions, or locator strings anywhere in the JSON**
- `description` must be a plain English sentence — not a selector, not a variable
- `continue_on_failure` at the top level: set to `true` to allow smoke-test style runs
- Per-step `continue_on_failure: false` on the first action if it is a required precondition (e.g. login)
- Do NOT include `variables`, `extra`, or other optional fields unless the trace explicitly provides values for them

### After writing the workflow JSON

Verify that no step contains `css`, `xpath`, `selector`, or `locator` keys. If any are found, remove them — they do not belong in workflow JSON.

---

## Hook Self-Correction

After **every** Write or Edit tool call, read the tool result for `VIOLATION:` or `ERROR:` markers. If any are found, fix them immediately before writing the next file.

### Common violations and fixes

| Marker | Root cause | Fix |
|--------|-----------|-----|
| `VIOLATION: interactive locator not a Locator instance` | `_interact()` is called with a raw CSS string instead of a `Locator` object | Replace with `Locator(css="...", description="...")` and import `from poms.shared.locator import Locator` |
| `VIOLATION: missing resolver injection` | `_build_pom` call is missing `page=page` and/or `resolver=resolver` | Add both keyword args: `self._build_pom(<POM>, driver, settings.base_url, page=page, resolver=resolver, behaviour=behaviour)` |
| `VIOLATION: raw page.locator in glue` | Glue file calls `page.locator()`, `page.get_by_role()`, etc. directly | Move the selector into the POM's `Locators` class as a cfg list entry; expose an interaction method (`click_<name>` or `fill_<name>`); call that method from glue instead |
| `VIOLATION: wrong import direction` | Glue or POM imports from `stepper/sites/` | Remove the import — glue imports from `poms/` only; POM never imports from `stepper/` |
| `ERROR: pyright type error` | Wrong type for `StepResult`, `StepConfig`, or `ExecutionContext` | Import exactly from `engine.interfaces`: `from engine.interfaces import StepConfig, StepResult, ExecutionContext` and use those types |

### Self-correction loop

1. Read the full tool result after each Write/Edit.
2. If it contains `VIOLATION:` or `ERROR:`, apply the minimal fix described in the table above.
3. Re-Edit the file to address the violation.
4. Read the result again — if the violation is gone, continue to the next file.
5. **False positive escape:** if the same code triggers the same `VIOLATION:` marker on a second attempt and you are confident the code is correct, log a one-line justification comment in the file and continue:
   ```python
   # hook-override: cfg list present, hook may have matched wrong line
   ```

---

## Error Handling

Apply the following checks in order at the very start of execution, before generating any files.

| Condition | Action |
|-----------|--------|
| `.stepper/trace.json` (or `--input` path) does not exist | Stop immediately: `Error: trace file not found — run /discover-site first` |
| `--site` argument is missing or empty | Stop immediately: `Error: specify --site short_code (e.g. --site sd)` |
| `poms/<site>/` or `stepper/sites/<site>/` already exists and `--force` is not set | Stop immediately: `Error: site already exists:\n  poms/<site>/\n  stepper/sites/<site>/\nPass --force to overwrite.` |
| `trace.pages` is an empty list or the key is absent | Stop immediately: `Error: trace is empty — no pages to generate from` |
| An individual element record has no selector key at all (no `role`, `label`, `placeholder`, `id`, `css`, `xpath`) | Write a comment placeholder in the cfg list and continue (do not crash): `# TODO: trace lacked all selectors for this element` followed by `<IDENTIFIER>_CFG: list = []` |
