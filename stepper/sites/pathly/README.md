# Pathly Studio — Stepper automation site

Pathly Studio is an **Electron** app, so it is the `web` domain reached a
different way. Every web action, every POM and the whole resolver cascade apply
unchanged; only where the `Page` comes from differs.

## You must start Pathly yourself

Nothing here launches it. The stepper *attaches* to a running Electron process
over the Chrome DevTools Protocol, and `run` refuses at plan time if nothing is
listening. That is deliberate: the session owns the CDP connection, not the
application, so teardown disconnects and leaves your window open.

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

If a testid is missing the resolver falls through rather than failing loudly,
so a silently skipped step usually means step 1 was not done.

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
