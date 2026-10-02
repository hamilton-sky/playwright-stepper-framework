# SauceDemo fixtures

A local stand-in for `www.saucedemo.com`, served on loopback so the `sd_*` flows
can run without the network.

## Why

The host is denied by this environment's egress policy. Of the five SauceDemo
workflows, only `sd_smoke_test` ever ran — in CI, against the live site — and
the hover-before-click rule applied to this site's collection clicks
(`add_to_cart_by_name`, `remove_from_cart_by_name`, `remove_item_by_name`) had
never been exercised by a browser.

Running the flows here found two defects on the first pass:

| | |
|---|---|
| `sd_sort_products` never checked the sort | It chose an option and returned `passed`. A page whose list ignored the selection still produced `5/5 passed`. It now reads the dropdown back **and** checks the products are in that order — `test_saucedemo_sort_is_verified.py`. |
| `--no-heal-cache` was ignored | `cmd_run` built a `RunConfig` with `use_heal_cache=False` and then left it out of the call to `pipeline.run()`, so every heal "measurement" replayed `heal_cache.json`. Pinned in `test_cli.py`. |

## Use

```bash
python stepper/sites/saucedemo/fixtures/server.py --port 8097 &
SAUCEDEMO_BASE_URL=http://127.0.0.1:8097 \
    python stepper/main.py run sd_happy_path \
    --vars '{"base_url": "http://127.0.0.1:8097"}'
```

**Two knobs, and you need both.** `SAUCEDEMO_BASE_URL` points the glue's POMs
here. `base_url` is the workflow variable that the engine-level steps
(`navigate`, `measure_performance`) interpolate. Set only one and a flow starts
on one host and finishes on the other.

| Workflow | Here |
|---|---|
| `sd_happy_path` | 6/6 — runs in CI |
| `sd_multi_product` | 9/9 — runs in CI; order total $36.69 = 33.97 + 8% tax |
| `sd_smoke_test` | 5/5 — runs in CI; the live-host run stays as the drift check |
| `sd_heal_test`, `sd_full_heal_flow` | not in CI. Run keyless with `--heal 2 --no-heal-cache`, `sd_heal_test` fails at step 2 — see below. |

## The keyless healer cannot recover the username field

CI ran `sd_heal_test` here with `--heal 2 --no-heal-cache` and every AI key unset.
Step 2 ("Type username into the username field", selector deliberately broken)
failed: the healer's `DOMSnapshotCascade` scored its best candidate between 0.50
and 0.85, returned `strategy=scoped` rather than `embed_direct`, and a scoped heal
needs an AI pick. With no provider, both attempts failed.

The input the healer embeds — tag `input`, placeholder `Username`, name
`user-name`, type `text` — is the same on the live site, so the long-standing
claim that this workflow heals "with no API key" very likely never held. It
went unmeasured because `--no-heal-cache` used to be ignored, so every run
replayed the committed `heal_cache.json`.

Open work: what `_describe_element` embeds, or where the 0.85 `embed_direct`
threshold sits. Until then the heal workflows need an LLM key.

## What it is and is not

The real site is a static single-page app: the session is a `session-username`
cookie and the cart is a JSON array of product ids in `localStorage` under
`cart-contents`. A static server is therefore a faithful model of its transport.
`app.js` reproduces that state and the DOM the POMs select on — class names,
`data-test` attributes, the 8% tax, the cart emptied on Finish, the
`Epic sadface:` errors (including `locked_out_user`), and a redirect to the login
page for an unauthenticated visit.

Two details are kept deliberately, because a fixture that smoothed them over
would hide what the cascade really does:

- the cart link is an `<a>` with **no href**, so it has no link role and
  `CART_LINK`'s `role="link"` falls through to CSS, as on the real site;
- the burger menu is in the DOM but **hidden** until opened.

The markup is a reconstruction, not a capture — the host could not be fetched.
A passing flow proves the selectors match *this* markup and the engine path
works end to end. It does not prove they still match the live site; CI's live
smoke run is what catches that drift.
