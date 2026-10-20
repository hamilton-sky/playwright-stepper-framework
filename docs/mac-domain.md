# The mac domain

`stepper/sites/mac/` drives the logged-in user's Mac: AppleScript, real mouse
events, keys, typing and screenshots. It is the domain
[stepper-mailbox](https://github.com/hamilton-sky/stepper-mailbox) runs every
job through, and it is the first domain that acts on a real computer rather
than on something the run opened itself.

It needs macOS, and it needs the Python that runs the workflow to be allowed
**Accessibility** (clicks, keys, typing, drags, element lookups) and **Screen
Recording** (screenshots) in System Settings > Privacy & Security. Preflight
refuses the run on any other platform.

```json
{"name": "open and follow a link", "domain": "mac", "steps": [
  {"action": "mac_run_script", "description": "open example.com",
   "extra": {"confirm": true, "script": "tell application \"Google Chrome\"\n activate\n open location \"https://example.com\"\nend tell"}},
  {"action": "mac_keypress", "description": "scroll to the bottom", "extra": {"key": "end"}},
  {"action": "mac_click", "description": "click Learn more",
   "extra": {"app": "Google Chrome", "element": "Learn more",
             "expect": {"window_title_contains": "Example Domains"}}}
]}
```

---

## Actions

| Action | `extra` | Notes |
|---|---|---|
| `mac_run_script` | `script`, **`confirm: true`** | Arbitrary AppleScript. Without `confirm` the step fails: a workflow file is remote code execution on the Mac, and the flag is the author saying so. What the script returns is in `output.output`. |
| `mac_click` | `x`, `y` · or `relative: "window"` + `x`, `y` · or `element` · `app`, `raise` | A real CoreGraphics click. See [Aiming](#aiming). |
| `mac_drag` | `x1`, `y1`, `x2`, `y2`, `steps` (20) · `relative: "window"`, `app`, `raise` | Press, interpolated drags, release. |
| `mac_keypress` | `key` (`"return"`, `"t"`, `"cmd+t"`, `"cmd+shift+left"`), `modifiers` | See [Keys](#keys). |
| `mac_type` | `text` | Types into the front app (System Events `keystroke`). |
| `mac_screenshot` | `path` | All displays, PNG, via `screencapture`. |

Every action takes `timeout_s` (default 30). Every action except
`mac_screenshot` takes [`expect`](#expect).

## Aiming

`mac_click` has three ways to say where. `mac_drag` has the first two.

1. **Screen points**: `{"x": 416, "y": -104}`. The origin is the top-left of the
   main display; displays above or left of it have negative coordinates.
   Simple, but stale as soon as a window moves, goes full screen, or a display
   is plugged in.
2. **Window-relative**: `{"app": "Google Chrome", "relative": "window", "x": 686, "y": 810}`.
   `x`/`y` are points from the top-left of the app's front window, which is
   looked up when the step runs. Without `app`, the frontmost app is used.
3. **By element**: `{"app": "Google Chrome", "element": "Learn more"}`, or
   `{"element": {"text": "Learn more", "match": "contains", "role": "AXLink", "wait_s": 10}}`.
   The first element whose accessibility title, description or value matches
   (case and whitespace ignored; an exact match beats a `contains` match) is
   clicked at its centre. If it is outside the visible window, the step fails
   with "scroll it into view first" rather than clicking somewhere else.

Window and element targets **raise the app's window first** (`"raise": false`
to skip). A window on top would otherwise take the click.

The step's `output.target` says how it aimed: `"screen"`, `"window '…'"` or
`"element '…'"`.

### Chrome and Electron pages

A browser builds the accessibility tree for page content only once an assistive
client asks for it. An element lookup sets `AXEnhancedUserInterface` (Chrome)
and `AXManualAccessibility` (Electron) on the app, waits up to `wait_s` for the
page's elements to appear, and then **restores the previous
`AXEnhancedUserInterface` value**. Leaving it on changes how some apps animate
and resize windows.

Measured on one Mac: window frame 0.1 s, a toolbar button 0.1 s, text inside a
Chrome page about 2–4 s (mostly Chrome building the tree). Page text is often
split into several elements: "Planforge" rendered as "plan" + "forge" will not
match `"Planforge"`.

## Keys

`key` is a name or one character, optionally with modifiers joined by `+`:

| | |
|---|---|
| names | `return` `enter` `tab` `space` `escape`/`esc` `delete`/`backspace` `forwarddelete` `up` `down` `left` `right` `pageup` `pagedown` `home` `end` `f1`…`f12` |
| modifiers | `cmd`/`command` `shift` `opt`/`option`/`alt` `ctrl`/`control` |
| examples | `"cmd+t"`, `"cmd+shift+left"`, `"cmd++"` (cmd and the + key), `{"key": "t", "modifiers": ["ctrl"]}` |

Anything else fails the step instead of guessing. `pagedown`, `pageup`,
`home` and `end` are how a workflow scrolls.

## expect

```json
"expect": {"front_app": "Google Chrome", "window_title_contains": "Example Domains",
           "element": "Further Reading", "timeout_s": 5}
```

After the action succeeds, the step keeps checking every 0.5 s until every
condition holds or `timeout_s` runs out. Then it **fails**, saying what it saw
instead (`front window is titled 'Example Domain', expected it to contain …`).

This exists because "the click was sent" and "the click worked" are different
claims. Before it, a `mac_click` that reached nothing (see below) reported
`passed`.

- `front_app` matches if either name contains the other, so `"Google Chrome"`
  matches Chrome's own name `"Chrome"`.
- `element` is looked up in the front window of `front_app` (or the front app).

## How it is built

- `session.py`: `MacHandle` runs every OS call in a subprocess with a timeout.
  Errors come back as `(False, text)`, never as exceptions.
- **Mouse** (`_MOUSE_PY` in `session.py`): `click` and `drag` modes post
  CoreGraphics events through stdlib `ctypes`. No pyobjc, nothing to install.
- **Accessibility** (`_ax_child.py`): `front`, `frame` and `find` modes call
  AXUIElement directly through `ctypes`. Its matching logic (`pick`,
  `label_matches`, `parse_args`) is pure and unit-tested on any platform.
- **Keys and typing** go through System Events (`key code`, `keystroke`).

### Why `mac_click` is not System Events `click at`

The first version ran `tell application "System Events" to click at {x, y}`.
That is not a mouse click: it asks the accessibility element under the point
to press itself. Chrome's web content ignores it, and `osascript` still exits 0.
A click on a link "passed" at exactly the right coordinates while the page
never changed. It took a real job and a screenshot afterwards to notice.
`mac_click` now posts the same mouse events a hand would.

## Startup cost

A mac run never resolves an element through the web resolver, so it should not
pay for the semantic model. `SemanticResolver` loads sentence-transformers (and
torch) on its first `score()`, not when it is built. A one-step `mac_run_script`
workflow takes about 0.4 s. Before that change it took ~4 s warm and ~25 s
cold, almost all of it importing torch.
`test_a_noop_run_never_loads_the_embedding_model` holds the line.

## Tests

`stepper/tests/unit/test_mac_domain.py` runs on any OS against a fake
`MacHandle`, so no events are posted. It covers:

- the mouse route,
- the three ways of aiming,
- off-screen elements,
- raising the window,
- key combos,
- `expect` met and unmet,
- the Accessibility child's matching and argument parsing.

The real end-to-end check is stepper-mailbox's `python -m stepper_mailbox smoke`:
open example.com, scroll, click "Learn more" by its label, and expect the IANA
page.

## Known gaps

- **No scroll wheel.** Scrolling is page keys. A `mac_scroll` with real wheel
  events would need a new action name, and machines that allowlist actions by
  name would have to allow it.
- **Element lookup is only as good as the app's accessibility tree.** Canvas
  apps, games and some custom UI expose nothing useful.
- **`app` is matched by process name** (`pgrep -x`), so the name must be the
  process's name: `"Google Chrome"`, not `"Chrome"`.
