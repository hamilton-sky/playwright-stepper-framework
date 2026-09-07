# Playwright Pitfalls the POM Layer Guards Against

Five failure modes that shaped how the OpenLibrary POMs are written. Each one is a
real bug pattern in Playwright automation; each section points at the code in this
repo that defends against it.

Two of the five — pagination and the missing `await` — fail *silently*: they pass on
small datasets and go wrong on real ones. Those are the ones worth internalising.

| # | Failure mode | Category | How it shows up | Guarded in |
|---|---|---|---|---|
| 1 | Year parsing crash | Unsafe type conversion | `ValueError`, loop dies | `poms/openLibrary/utils/book_filter.py` |
| 2 | Wrong pagination selector | Wrong CSS selector | **Silent** under-count | `poms/openLibrary/pages/reading_list_page.py` |
| 3 | Illegal characters in file path | Missing sanitisation | `OSError` on first screenshot | `examples/plain_pom/flows.py` |
| 4 | Wrong shelf-button selector | Wrong CSS selector | `TimeoutError`, nothing shelved | `poms/openLibrary/pages/book_detail_page.py` |
| 5 | Missing `await` | Async misuse | **Silent** wrong assertion | everywhere — see below |

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
(`stepper/engine/actions/strategies.py` → `ParallelAction`) worth having.
