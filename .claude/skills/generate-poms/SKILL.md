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

**`poms/<site>/config.py`** — settings loader. Do **not** hand-roll the
DEFAULTS → config.yaml → environment merge: `poms/shared/config.py` owns that
algorithm, and its docstring records what three private copies cost last time
("Three copies, drifting independently — phpTravels' had already lost YAML
support"). Copy the shape of `poms/saucedemo/config.py`: a frozen `Settings`
dataclass with this site's own fields, `DEFAULTS`, `ENV_MAP`, and a
`load_settings()` that calls `load_config_data(...)`.

Credentials are fields on `Settings` read from the environment — never literals
in the generated file, and never values carried over from the trace.

**`stepper/sites/<site>/register.py`** — site registration entry point. The engine's `register_all_sites()` auto-discovers this file via `stepper/sites/*/register.py` glob. Without it, all generated actions are invisible at runtime.

Generate it after all glue files are written, importing every `PageModule` subclass and calling `.register(registry)`:

```python
def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.<site>.pages.<action_group>_action import <Site><Page>Page
    # ... one import per glue PageModule class ...

    <Site><Page>Page.register(registry)
    # ... one register call per PageModule class ...
```

Imports are `stepper.sites.<site>.pages.<module>` — fully qualified, because the
package is installed (`pip install -e .`) and a bare `sites.` prefix does not
resolve. Every shipped `register.py` does it this way; check one rather than
trusting this snippet. List imports in the same order glue files were generated.

The imports are **inside** the function on purpose: `register_all_sites` imports
every site's `register.py` at startup, and a module-level `poms` import there
would pull the POM layer — and Playwright with it — into runs that never touch
a browser.

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

Do not generate from a template pasted here — that is how this skill drifted
the first time: its inlined glue template froze in May while
[.claude/rules/glue-layer.md](../../rules/glue-layer.md) moved on, so it
generated code that no longer imported.

Read that rule file, then copy the structure of
`stepper/sites/saucedemo/pages/login_action.py`, which is the canonical
example. The points it is easiest to get wrong:

- Imports are `from stepper.engine....` — the package is installed
  (`pip install -e .`), so the bare `engine.` prefix does not resolve.
- Register through `cls.register_actions(registry, cls.MyAction())`, never
  `registry.register(...)` directly. `register_actions` is what enforces the
  `<site>_` prefix and stamps the action's domain; calling `register` by hand
  skips both.
- One `PageModule` per logical page, actions as nested `GlueAction` classes.
- `_execute` takes five parameters and `behaviour` **must** default to `None`
  — sub-step dispatch passes nothing.
- Never override `execute()`. It is the template method.
- `PageModule.domain` defaults to `"web"`, which is what a website wants.
  Leave it alone. (A domain with no pages — a database, an HTTP API — is a
  different shape entirely: no POMs, and actions subclassing `ActionStrategy`
  rather than `GlueAction`. See `stepper/sites/db/` if that is what you are
  generating, and note that this skill is not for that case.)

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
- No CSS / XPath strings hardcoded in glue — every selector lives in a POM's `Locators` class as a `Locator` object
- No imports from other `stepper/sites/` directories
- No flow control beyond what is needed for a single atomic action

### After each glue Write

Read the tool result. If it contains `VIOLATION:` or `ERROR:`:
- `"missing resolver injection"` → add `page=page, resolver=resolver` to the `_build_pom` call
- `"raw page.locator in glue"` → move the selector into the POM's `Locators` class as a `Locator` object, expose a method, call that method from glue
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
| `VIOLATION: raw page.locator in glue` | Glue file calls `page.locator()`, `page.get_by_role()`, etc. directly | Move the selector into the POM's `Locators` class as a `Locator` object; expose an interaction method (`click_<name>` or `fill_<name>`); call that method from glue instead |
| `VIOLATION: wrong import direction` | Glue or POM imports from `stepper/sites/` | Remove the import — glue imports from `poms/` only; POM never imports from `stepper/` |
| `ERROR: pyright type error` | Wrong type for `StepResult`, `StepConfig`, or `ExecutionContext` | Import exactly from `stepper.engine.interfaces`: `from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext` and use those types |

### Self-correction loop

1. Read the full tool result after each Write/Edit.
2. If it contains `VIOLATION:` or `ERROR:`, apply the minimal fix described in the table above.
3. Re-Edit the file to address the violation.
4. Read the result again — if the violation is gone, continue to the next file.
5. **False positive escape:** if the same code triggers the same `VIOLATION:` marker on a second attempt and you are confident the code is correct, log a one-line justification comment in the file and continue:
   ```python
   # hook-override: Locator object present, hook may have matched wrong line
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
| An individual element record has no selector key at all (no `role`, `label`, `placeholder`, `id`, `css`, `xpath`) | Write a `Locator` carrying only its description and continue (do not crash): `# TODO: trace lacked all selectors for this element` followed by `<IDENTIFIER> = Locator(description="<name> — no selectors in trace")` |

---

## Next Step

After all files are written, print:

```
Generation complete.
  POMs:     poms/<site>/pages/
  Glue:     stepper/sites/<site>/pages/
  Workflow: stepper/sites/<site>/workflows/<flow_name>.json

Next:
  /verify-layers                              audit the three-layer contract
  python stepper/main.py validate             every workflow, no browser — the
                                              new one must appear and be valid
  python stepper/main.py run <flow_name>      run it for real
```
