# the-internet fixtures

A local stand-in for `the-internet.herokuapp.com`, served on loopback so the
`ti` workflows can actually run.

## Why

`ti` was generated from a crawl and shipped with eight workflows. Six had never
been run: this environment's egress policy denies that host —

```
connect_rejected: gateway answered 403 to CONNECT
                  host: the-internet.herokuapp.com:443
```

— so `validate` ("the wiring is sound") was the strongest claim anyone could
make about them. That is not a small gap. The one flow that *had* run is where
the `role=checkbox name="checkbox 1"` bug turned up, and running these six
turned up another: `HoversPage` used `.figure:nth-child(1) img`, which matches
**nothing**, and the flow reported 1/1 passed anyway.

## Use

```bash
python stepper/sites/ti/fixtures/server.py --port 8099 &
TI_BASE_URL=http://127.0.0.1:8099 python stepper/main.py run hover_over_elements_to_reveal_hidden_text
```

`127.0.0.1` is in the proxy's `noProxy` list, so nothing here touches the
network. `TI_BASE_URL` is the site's existing knob — no code changes to point
the whole site at these pages.

## What is covered

| Path | Exercises |
|---|---|
| `/checkboxes` | sibling text nodes with no `<label>` — the accessible-name trap |
| `/dropdown` | native `<select>`, driven by `select_option` rather than the cascade |
| `/drag_and_drop` | HTML5 drag-and-drop; dropping swaps the columns, so the result is observable |
| `/hovers` | `.figcaption { display: none }` revealed by `:hover` — the link exists but is unclickable until hovered |
| `/javascript_alerts` | the three native dialogs, and a `#result` that records which |
| `/windows`, `/windows/new` | `target="_blank"`, for `expect_page()` |
| `/login`, `/authenticate`, `/secure`, `/logout` | a real form POST, a session cookie, two redirects and both flash messages |
| `/users/{n}` | 404, as on the real site — which is what makes the hover flow's click observable |

## What this is not

The markup is a **reconstruction**, not a capture: the host is unreachable from
here, so it could not be fetched. It reproduces the structures the POMs select
on — element ids, the login form's action and labels, the hover CSS, the
sibling-text checkboxes, `target=_blank`, the three dialogs.

Two things deliberately differ, and say so where they differ: avatars are
inline `data:` URIs rather than `/img/*.jpg`, and the session is a plain cookie
rather than Rack's signed one.

**So a passing flow proves the selector matches *this* markup and that the
engine path behind it works end to end. It does not prove the selector still
matches the live site.** When the host becomes reachable, run the same eight
workflows with `TI_BASE_URL` unset; any disagreement is a fixture that has
drifted, and the fixture is what should change.
