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

2. Build a cfg list named `<IDENTIFIER>_CFG`. Priority order:
   - `role` + `name` → priority 10 (include only if both are non-empty)
   - `label` → priority 20 (include only if non-empty)
   - `placeholder` → priority 30 (include only if non-empty)
   - `id` → priority 40 (include only if non-empty AND not volatile)
   - `css` → priority 50 (include only if non-empty)
   - Volatile id: if `id` matches `[a-z0-9]{8,}` or contains a hex suffix (`^[a-z]+-[a-f0-9]{4,}$`), assign priority 60 instead of 40

3. If an element has no selector keys at all, write:
   ```python
   # TODO: trace lacked all selectors for this element
   <IDENTIFIER>_CFG: list = []
   ```

Example cfg list:
```python
class Locators:
    USERNAME_CFG = [
        {"role": "textbox", "name": "Username", "priority": 10},
        {"label": "Username",                   "priority": 20},
        {"placeholder": "Username",             "priority": 30},
        {"id": "user-name",                     "priority": 40},
        {"css": "[data-test='username']",       "priority": 50},
    ]
    LOGIN_BUTTON_CFG = [
        {"role": "button", "name": "Login",     "priority": 10},
        {"css": "[data-test='login-button']",   "priority": 50},
    ]
    # Read-only state (not interactive — plain string, no cfg list)
    ERROR_MSG = "[data-test='error']"
```

**Rule:** every cfg list entry must have a `"priority"` key. Never omit it.

### Methods

For each interactive element:
- If textbox / textarea / searchbox: `async def fill_<identifier>(self, value: str) -> None` calling `await self._resolve_and_fill_any(self.Locators.<IDENTIFIER>_CFG, value)`
- If button / link / checkbox / combobox / select: `async def click_<identifier>(self) -> None` calling `await self._resolve_and_click_any(self.Locators.<IDENTIFIER>_CFG)`

### url property

```python
@property
def url(self) -> str:
    return f"{self.base_url}{page.path_suffix}"  # path_suffix derived from page.url
```

### wait_for_ready

```python
async def wait_for_ready(self) -> None:
    first_cfg = self.Locators.<FIRST_INTERACTIVE>_CFG
    if first_cfg:
        top = min(first_cfg, key=lambda c: c["priority"])
        # wait using highest-priority selector available
        try:
            if "css" in top:
                await self._driver.wait_for_selector(top["css"], timeout=15_000)
            elif "id" in top:
                await self._driver.wait_for_selector(f"#{top['id']}", timeout=15_000)
        except Exception:
            pass
```

### Full generated POM file shape

```python
"""<site>/pages/<slug>_page.py — Pure POM for <Title> page."""
from __future__ import annotations
import logging
from poms.<site>.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class <PageClass>(BasePage):

    class Locators:
        <IDENTIFIER>_CFG = [...]
        ...

    @property
    def url(self) -> str:
        return f"{self.base_url}/<path>"

    async def wait_for_ready(self) -> None:
        ...

    async def fill_<name>(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.<NAME>_CFG, value)

    async def click_<name>(self) -> None:
        await self._resolve_and_click_any(self.Locators.<NAME>_CFG)
```

### After each POM Write

Read the tool result. If it contains `VIOLATION:` or `ERROR:`:
- `"interactive locator not in cfg list"` → convert the plain string/Locator to a cfg list with at least one `{"css": ..., "priority": 50}` entry
- Any other violation → apply the minimal fix described in the message
- Re-Edit the file before writing the next POM
- If the hook output appears to be a false positive (same code passes on second attempt), log a one-line justification and continue
