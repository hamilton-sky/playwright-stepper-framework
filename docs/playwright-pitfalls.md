# Playwright Pitfalls the POM Layer Guards Against

Seven failure modes that shaped how the POMs are written. Each one is a real bug
pattern in Playwright automation; each section points at the code in this repo that
defends against it.

Four of the seven fail *silently* — they pass on small datasets, fast machines or
recorded fixtures, and go wrong on real ones. Those are the ones worth internalising.
The last two were found in this repo's own code, by CI runs that were green.

| # | Failure mode | Category | How it shows up | Guarded in |
|---|---|---|---|---|
| 1 | Year parsing crash | Unsafe type conversion | `ValueError`, loop dies | `poms/openLibrary/utils/book_filter.py` |
| 2 | Wrong pagination selector | Wrong CSS selector | **Silent** under-count | `poms/openLibrary/pages/reading_list_page.py` |
| 3 | Illegal characters in file path | Missing sanitisation | `OSError` on first screenshot | `examples/plain_pom/flows.py` |
| 4 | Wrong shelf-button selector | Wrong CSS selector | `TimeoutError`, nothing shelved | `poms/openLibrary/pages/book_detail_page.py` |
| 5 | Missing `await` | Async misuse | **Silent** wrong assertion | everywhere — see below |
| 6 | Waiting on a load state, not the navigation | `await` on the wrong thing | **Silent**, timing-dependent | `poms/saucedemo/pages/login_page.py` |
| 7 | An assertion that resolves fuzzily | Forgiving lookup in an unforgiving place | **Silent** false pass | not yet guarded — see below |

Numbers 6 and 7 share a shape with 5 and are worth reading together: in each, the
code does something reasonable-looking and the run goes green while the thing it was
supposed to check never happened.

---

## 1. `int()` on `inner_text()` crashes the collection loop

`inner_text()` returns everything the element renders, not the one value you want:

```python
year_el   = await item.query_selector(".bookEditions")
year_text = await year_el.inner_text()
year      = int(year_text.strip())          # ValueError
```

The real text is `"First published in 1965 — 42 editions"`. `int()` raises immediately,
and because the call sits inside a loop over every search result, *zero* books are
collected — one unparseable row kills the whole run.

**The guard** — `poms/openLibrary/utils/book_filter.py`:

```python
def extract_year_from_text(text: str) -> list[int]:
    m = re.search(r"First published in (\d{4})", text or "")
    if m:
        return [int(m.group(1))]
    return [int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text or "")]
```

Two things make this more robust than a bare `\d{4}` search:

- It **anchors on the label first**. `"First published in 1965 — 42 editions"` contains
  two numbers; anchoring picks the right one rather than the first one.
- The fallback is **range-bounded** (`1[0-9]{3}|20[0-2][0-9]`), so an edition count or
  an ISBN fragment can't be mistaken for a year.
- `text or ""` makes a `None` argument return `[]` instead of raising.

It returns a *list*, so "no year found" is an empty list rather than an exception —
callers filter with `is_under_year()`, which is false for an empty list. The function
is pure: no driver, no page, no Playwright, so it is directly unit-testable.

## 2. A selector that matches nothing breaks pagination in silence

```python
_NEXT_PAGE_CSS = "a.next-page, a[rel='next']"     # neither exists on OpenLibrary
```

`query_selector` returns `None` on every page, so the pagination loop breaks after
page 1 — *without raising*. Tests pass on an account whose books fit on one page and
under-count on any account that doesn't. Nothing in the output says so.

**The guard** — `poms/openLibrary/pages/reading_list_page.py`:

```python
NEXT_PAGE = "a.ChoosePage[data-ol-link-track='Pager|Next']"
```

This targets a `data-*` attribute. Those exist for analytics and JS hooks rather than
styling, which makes them markedly more stable than visual class names — a redesign
rewrites `.next-page`, but `Pager|Next` survives because tracking code depends on it.

Verify a selector before trusting it. In DevTools:

```js
document.querySelectorAll("a.ChoosePage[data-ol-link-track='Pager|Next']")
```

An empty `NodeList` means the selector is wrong, whatever it looks like.

> A selector that matches nothing and a page that has nothing look identical to
> `query_selector`. When "no next page" and "broken selector" produce the same value,
> a wrong selector cannot fail loudly. Prefer the resolver cascade
> (see [resolver-cascade.md](../.claude/rules/resolver-cascade.md)) for interactive
> elements — it reports *how* it found the element and with what confidence, which
> turns this class of silence into a log line.

## 3. A URL is not a filename

```python
await page.screenshot(path=f"screenshots/{url}.png")
```

With `url = "https://openlibrary.org/works/OL123W/Dune"` that asks the OS to create
`screenshots/https://openlibrary.org/works/OL123W/Dune.png`. Both `://` and `/` are
illegal in filenames on Linux and Windows alike, so this raises on the first shot.

**The guard** — `examples/plain_pom/flows.py`:

```python
slug = re.sub(r"[^\w\-]", "_", url.split("/")[-1])[:60]
```

- `url.split("/")[-1]` keeps only the last path segment.
- `[^\w\-]` matches anything that is *not* a word character or hyphen, and replaces it
  with `_`. Allow-list, not deny-list: you cannot forget to ban a character.
- `[:60]` caps the length — most filesystems reject names past 255 bytes, and OpenLibrary
  slugs can be long.

Note that `ScreenshotManager.capture(name)` does **not** sanitise; it takes a name and
writes `<name>.png`. Sanitisation is the caller's job, which is why it lives at the
call site in `flows.py` and in `stepper/sites/openlibrary/pages/detail_page.py`.

## 4. A plausible-looking selector that does not exist

```python
await page.click(".want-to-read-btn")           # class never existed
```

`click()` waits for the selector, hits its timeout, and raises `TimeoutError` — once per
book, so a five-book run costs five timeouts before failing.

**The guard** — `poms/openLibrary/pages/book_detail_page.py` defines the button as a
`Locator` with an ordered set of fallbacks rather than one string:

```python
SHELF_BTN_BASE        = "button.book-progress-btn"
SHELF_BTN_ACTIVATED   = "button.book-progress-btn.activated"
SHELF_BTN_UNACTIVATED = "button.book-progress-btn.unactivated"
SHELF_BTN_PRIMARY     = "button.book-progress-btn.primary-action"
ADD_SELECTORS = [SHELF_BTN_UNACTIVATED, SHELF_BTN_PRIMARY, SHELF_BTN_BASE, SHELF_BTN_ACTIVATED]
```

Chained classes mean the element must carry **both**: `book-progress-btn` identifies the
shelf-button family, `unactivated` narrows it to books not yet shelved. Most specific is
tried first, so the run degrades through the list instead of failing outright.

## 5. A coroutine is not a result

```python
actual = reading_list.get_book_count()      # no await
assert actual == expected_count
```

`get_book_count` is `async def`, so calling it without `await` doesn't run it — it
returns a coroutine object. The assertion then compares a coroutine to an int. Different
types are never equal in Python, so this is always `False`… and a coroutine object is
*truthy*, so under `assert actual` styles the test passes without counting anything.

Python does warn — `RuntimeWarning: coroutine 'get_book_count' was never awaited` — but
only in the log, which is exactly where nobody looks when a test is green.

```python
actual = await reading_list.get_book_count()
```

Every POM method that touches the page is `async`, so every call needs `await`. Two
things make this catchable rather than a matter of vigilance:

- Pyright flags the type mismatch statically. The repo runs it as a `PostToolUse` hook
  (`.claude/hooks/pyright-check.py`) so it fires on every edit.
- `asyncio_mode = "auto"` in `pyproject.toml` means pytest handles the event loop, so
  tests can `await` without per-test decorators — one less thing to forget.

Playwright is async because every operation waits on the browser. `await` yields the
thread during that wait instead of blocking it, which is what makes parallel actions
(`stepper/engine/actions/flow.py` → `ParallelAction`) worth having.


---

## 6. `wait_for_load_state` does not wait for the navigation you just triggered

```python
await self._interact(self.Locators.SUBMIT, "click")
await self._driver.wait_for_load_state("domcontentloaded")
```

This looks like "click, then wait for the new page". It is not.
`wait_for_load_state` reports on the **current** document, and immediately after the
click the current document is still the login page — already loaded — so it returns
at once, before the new page commits.

The caller then reads the old DOM. In this repo that produced:

```
sd_login: login failed — unknown error
```

for a login that was about to succeed. The empty error message is the tell: a real
credential rejection puts a banner on the page, so "no logo *and* no error" means the
page simply had not changed yet.

It fails only when the navigation is slower than the check, so it passes locally and
on most CI runs and then does not — the worst shape a failure can have. It survived
here until a CI run on an unrelated change happened to be slow enough.

**The guard** — `poms/saucedemo/pages/login_page.py`:

```python
async def _settle_after_submit(self, timeout: int = 10_000) -> None:
    outcome = f"{self.Locators.APP_LOGO}, {self.Locators.ERROR_MSG}"
    try:
        await self._driver.wait_for_selector(outcome, timeout=timeout)
    except Exception as exc:
        log_swallowed("LoginPage._settle_after_submit", exc, logger)
    await self._driver.wait_for_load_state("domcontentloaded")
```

Wait for a selector that only exists **after** the submit resolved, and accept either
outcome — the inventory logo on success, the error banner on failure. Both branches
become deterministic; waiting only for the success marker would stall the full
timeout on every genuine bad-credentials run.

`poms/phpTravels/pages/login_page.py` still has the original shape. OpenLibrary's
does not — it polls `current_url` until it leaves `/account/login`, which is another
correct way to express the same wait.

---

## 7. An assertion that resolves fuzzily is not an assertion

This one is still live, and is recorded here because it is a design decision rather
than a typo.

`assert_visible` and `assert_text` find their element the same way every other action
does:

```python
result = await resolver.resolve(page, step.element, step.description)
```

That is the full cascade — deterministic strategies, then the semantic filter, then
`KeywordFuzzyResolver`, which matches against the step's **description** when the
selector finds nothing:

```
Deterministic cascade failed — falling through to zero-selector path
✓ [keyword-fuzzy] single match → confidence 85%
```

For an action that *does* something, that forgiveness is the entire point: you want
the click to land even after a redesign. For an action that *checks* something, it
removes the only thing the check was for. An assertion written

```json
{ "action": "assert_visible",
  "description": "Inventory page rendered",
  "element": { "css": ".app_logo" } }
```

passes on a page with no `.app_logo` at all, by matching some other element against
the words "Inventory page rendered".

That is how a heal-test workflow in this repo reported `0 failed` while the login it
existed to verify had never happened — the assertion could not fail.

**No guard yet.** Fixing it means an exact-match mode for the `assert_*` actions, so
an assertion resolves deterministically and fails when its element is absent. That
changes assertion semantics for every existing workflow — some that pass today would
start failing, several of them rightly — so it is a deliberate decision rather than a
patch.

Until then: an `assert_*` step is a strong signal when it fails and a weak one when
it passes. Prefer `assert_count` with an exact expectation, or check state through a
POM method that reads the DOM directly (`locator_count`, `is_logged_in`), which do
not go through the resolver.
