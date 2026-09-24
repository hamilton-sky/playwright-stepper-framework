# Pathly Studio — Stepper automation site

Pathly Studio is an **Electron** app, so it is the `web` domain reached a
different way. Every web action, every POM and the whole resolver cascade apply
unchanged; only where the `Page` comes from differs.

## You must start Pathly yourself

Nothing here launches it. The stepper *attaches* to a running Electron process
over the Chrome DevTools Protocol. That is deliberate: the session owns the CDP
connection, not the application, so teardown disconnects and leaves your window open.

`run` refuses at plan time when `STEPPER_ELECTRON_CDP_PORT` is set and nothing
answers on it. **Unset, there is nothing to refuse on**: preflight falls back to
checking for an installed browser, the run launches an ordinary Chromium, and the
first step fails against a page that was never Pathly. So always set it.

```bash
# 1. in the Pathly Studio checkout — start it with CDP enabled, and wait for
#    the HomeScreen to appear
npm run dev -- --remote-debugging-port=9222

# 2. here
STEPPER_ELECTRON_CDP_PORT=9222 python stepper/main.py run pathly_smoke
```

If the port is closed you get a plan-time refusal in milliseconds rather than a
thirty-second retry:

```
error: 1 domain(s) this workflow needs are not ready here:
  web: nothing is listening on CDP port 9222 (STEPPER_ELECTRON_CDP_PORT is set),
       so there is no Electron app to attach to — start it with
       --remote-debugging-port=9222
```

`STEPPER_ELECTRON_TIMEOUT_MS` (default 30000) bounds how long the attach waits
for a still-booting app.

## The selectors live in the other repo

Every locator here is a `data-testid` that must exist in Pathly Studio's own
source. Adding an element to this harness is two changes in two repositories:

1. **In `pathly-adapters`** — add `data-testid="<screen>-<element>"` to the JSX
   in `studio/src/renderer/src/components/`, and check it compiles.
2. **Here** — add a `Locator` to the matching POM's `Locators` class, a method
   that calls `self._interact(...)`, and a glue action that calls that method.

If a testid is missing, the resolver finds nothing and `_interact` returns
False — it does not raise. Each glue action here checks that flag and reports
the step **failed**, naming the action:

```
✗ pathly_open_wizard: the element did not resolve on the attached page
  — wrong screen, or the data-testid is missing from Pathly Studio
```

That check is the difference between a red run and a green lie. Without it
`pathly_wizard_smoke` — nine interactions and a screenshot, no assertion
anywhere — reported ten passed steps against an app whose wizard never opened.
`stepper/tests/unit/test_pathly_failure_propagation.py` holds both halves of
the rule: no POM method may discard `_interact`'s result, and no glue action
may return `passed` when it is False.

## Waiting for a screen

A `wait` step takes `wait_for` — a selector or a URL fragment — as a top-level
field, not a duration inside `extra`:

```json
{ "action": "wait", "description": "Wait for the HomeScreen to be ready",
  "wait_for": "[data-testid=\"homescreen-tab-projects\"]" }
```

`WaitAction` reads `wait_for` and `input_value` and nothing else. A `wait` step
carrying `extra: {"timeout": 5000}` or `extra: {"ms": 1000}` does not wait five
seconds or one — the fields are ignored and it sleeps a flat two. Both of these
workflows shipped that way until the readiness selectors above replaced them.
Name the element you are waiting for; a number would be a guess about a machine
you are not on.

## What this site can drive

| Action | What it does |
|---|---|
| `pathly_open_project` · `pathly_new_project` · `pathly_assert_projects` | home screen |
| `pathly_navigate_panel` · `pathly_toggle_chat` | top bar and sidebar |
| `pathly_read_routing` · `pathly_set_routing` · `pathly_save_settings` | settings |
| `pathly_open_wizard` · `pathly_wizard_select_template` · `pathly_wizard_set_name` · `pathly_wizard_next` · `pathly_wizard_save` | FlowWizard |

## Status

**Never run against a live Pathly.** It was written in May against an app this
environment cannot reach, and brought up to the current conventions without
being exercised. Treat the first run as a bring-up, not a regression check —
`validate` proves the wiring, not the selectors.
