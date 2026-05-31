# Pathly Studio — Stepper Automation Site

End-to-end automation harness for Pathly Studio (Electron) using the Playwright Stepper framework.

## Prerequisites

- Python 3.x with Playwright installed (`pip install playwright && playwright install chromium`)
- Pathly Studio checked out at `C:\Users\Yafit\pathly-adapters\studio\`
- Start Studio with CDP enabled (PowerShell):

  ```powershell
  cd C:\Users\Yafit\pathly-adapters\studio
  $env:ELECTRON_ENABLE_LOGGING=1
  npm run dev -- --remote-debugging-port=9222
  ```

- Wait for the HomeScreen to appear before running workflows.

## Running the smoke workflow

```powershell
cd C:\Users\Yafit\playwright-stepper-framework
python stepper/main.py --browser electron --cdp-port 9222 --workflow stepper/sites/pathly/workflows/pathly_smoke.json
```

## Adding a new element to the harness (4 steps)

**Step 1 — Add data-testid in Studio** (in `pathly-adapters` repo):
Open the relevant component in `studio/src/renderer/src/components/`. Add `data-testid="myscreen-myelement"` to the target JSX element. Run `npx tsc --noEmit` to confirm no type errors.

**Step 2 — Add locator and method to the POM** (in this repo):
Open `poms/pathly/pages/<screen>_page.py`. Add a locator property:
```python
@property
def _my_element(self):
    return self.page.locator('[data-testid="myscreen-myelement"]')
```
Add a method that uses it.

**Step 3 — Add a glue action** (in this repo):
Open `stepper/sites/pathly/pages/<screen>_action.py`. Add an inner `GlueAction` subclass and register it in the `register()` classmethod.

**Step 4 — Use in a workflow**:
Add a step to the relevant workflow JSON:
```json
{ "action": "my_new_action", "description": "Do the thing", "extra": { "param": "value" } }
```

## data-testid naming convention

Format: `{component}-{element}-{variant}` — all lowercase kebab.
Examples: `homescreen-tab-projects`, `topbar-panel-flow`, `settings-routing-llm`.

## Settings safety note

`pathly_settings.json` is read-only. Do not add `pathly_save_settings` to automated workflows without first setting up a sandbox config directory. Writing to the developer's real Pathly config from a test is not supported in v1.
