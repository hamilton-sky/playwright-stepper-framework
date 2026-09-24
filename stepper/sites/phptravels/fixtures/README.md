# phpTravels fixtures

A local stand-in for `phptravels.com`, served on loopback so the `pt_*` flows
can actually run.

## Why

phpTravels shipped four actions and one workflow, and **none of them had ever
run**. The host is denied by this environment's egress policy, and unlike
SauceDemo there was no CI step for the site at all — so `validate` ("the wiring
is sound") was the whole of what anyone knew about it.

Running it found two defects in the first two attempts:

| | |
|---|---|
| `HotelDetailPage.__init__` omitted `behaviour` | `_build_pom` passes it to every POM, so `pt_book_hotel` died on `TypeError: unexpected keyword argument 'behaviour'` — caught by the glue's `except Exception` and reported as an ordinary failed step. **The last step of the site's only workflow had never once run.** |
| the typeahead suggestion was a `Locator` | A typeahead offers several matches by design; the cascade resolves exactly one and refuses 2+. Typing "Dubai" gave two suggestions and the step failed. It could only ever have worked on a query with exactly one match. |

The first also turned up in `saucedemo`'s `ProductPage` once the rule went
repo-wide (`test_pom_behaviour_optional.py`).

## Use

```bash
python stepper/sites/phptravels/fixtures/server.py --port 8098 &
PHPTRAVELS_BASE_URL=http://127.0.0.1:8098 \
PHPTRAVELS_EMAIL=user@phptravels.com PHPTRAVELS_PASSWORD=demouser \
    python stepper/main.py run hotel_booking
```

`PHPTRAVELS_BASE_URL` is the site's existing knob — no production code changes
to point it here. `127.0.0.1` is in the proxy's `noProxy` list, so nothing
touches the network.

## What is covered

| Path | Exercises |
|---|---|
| `/` | the `.tt-menu` typeahead the search flow waits on, and `#hotels` / `#flights` tabs that give **two** buttons both named "Search" — so the role strategy is genuinely ambiguous and the cascade must fall through to CSS, as on the real site |
| `/account/login`, `/account` | a real form POST, a session cookie, a redirect, and the `.dropdown-toggle img.rounded-circle` avatar that `is_logged_in()` counts |
| `/hotels` | `.col-md-12.hotel-listing` cards the results POM parses for name, price and star count |
| `/hotels/{slug}` | the booking form, and `h1.hotel-name` that `wait_for_ready()` waits on |
| `/hotels/{slug}/book` | a confirmation carrying `.booking-ref` and `.booking-confirmed`, so the happy path is observable rather than assumed |

## What this is not

The markup is a **reconstruction, not a capture** — the host is unreachable
from here, so it could not be fetched. It reproduces the structures the POMs
select on, and nothing else: there is no styling, no real inventory, and the
session is a plain cookie.

**So a passing flow proves the selector matches *this* markup and that the
engine path behind it works end to end. It does not prove the selector still
matches the live site.** When the host becomes reachable, run the same workflow
with `PHPTRAVELS_BASE_URL` unset; any disagreement is a fixture that has
drifted, and the fixture is what should change.

One thing the fixtures deliberately do **not** paper over: the hotel links are
`/hotels/{slug}`, matching `HotelDetailPage.url`. The results POM's
`HOTEL_BOOK_BTN` is `"a.btn-primary, a[href*='hotel/']"`, and that second
alternative does not match `/hotels/…` — `hotel/` is not a substring of
`hotels/`. It works here because `a.btn-primary` matches first. If the live
site uses `/hotel/{slug}`, then `HotelDetailPage.url` is the thing that is
wrong, and only a run against the real host can say which.
