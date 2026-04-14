# Bug Analysis — Explained

A deep-dive companion to `ReadMeAIBugs.md`.
For each bug: what the code does wrong, why it matters, how it was fixed, and the underlying concept.

---

## Bug 1: Year Parsing Crashes on Real DOM Text

### The broken code
```python
year_el = await item.query_selector(".bookEditions")
if year_el:
    year_text = await year_el.inner_text()
    year = int(year_text.strip())
```

### What goes wrong
`inner_text()` returns everything the element renders visually — not just a number.
On OpenLibrary the text looks like:

```
"First published in 1965 — 42 editions"
```

`int("First published in 1965 — 42 editions")` raises a `ValueError` immediately.
Because this is inside a loop over every search result, the entire function crashes —
zero books are ever collected.

### The fix
```python
import re
match = re.search(r"\b(\d{4})\b", year_text)
if match:
    year = int(match.group(1))
```

### Concept: Regex for structured extraction

`inner_text()` gives you the human-readable string. To pull a specific piece out of it
you need pattern matching. `re.search` scans the string and returns the first match
of the pattern, or `None` if nothing matches — safe to check before calling `.group()`.

**Pattern breakdown:**
| Part | Meaning |
|---|---|
| `\b` | Word boundary — ensures we match a standalone 4-digit number, not part of a longer one |
| `(\d{4})` | Capture group — exactly 4 digits |
| `\b` | Word boundary again on the right side |

`match.group(1)` returns the content of the first capture group — the 4-digit year string.
`int(...)` then converts it safely because we know it contains only digits.

---

## Bug 2: Wrong CSS Selector for Pagination — Silent Failure on Multi-Page Lists

### The broken code
```python
_NEXT_PAGE_CSS = "a.next-page, a[rel='next']"
```

Used in the pagination loop:
```python
next_el = await self._driver.query_selector(self._NEXT_PAGE_CSS)
if not next_el:
    break  # loop exits here on EVERY page
await next_el.click()
```

### What goes wrong
Neither `a.next-page` nor `a[rel='next']` exist anywhere in OpenLibrary's HTML.
`query_selector` returns `None` on every single page — even when there are more pages.
The loop therefore breaks after page 1 every time, silently.

The danger here is that the code does not raise an error. Tests pass on small accounts
(all books fit on page 1) and fail mysteriously on large ones. This is a **silent correctness
failure** — the worst kind.

### The fix
```python
_NEXT_PAGE_CSS = "a.ChoosePage[data-ol-link-track='Pager|Next']"
```

### Concept: CSS attribute selectors and how to find the right selector

A CSS selector can target an element by:
- **Tag** — `a`, `button`, `li`
- **Class** — `a.next-page` means `<a class="next-page">`
- **Attribute** — `a[rel='next']` means `<a rel="next">`
- **Combined** — `a.ChoosePage[data-ol-link-track='Pager|Next']` means an `<a>` tag
  that has class `ChoosePage` AND a `data-ol-link-track` attribute equal to `Pager|Next`

`data-*` attributes are custom HTML5 data attributes that developers add for JavaScript hooks
or analytics. They are stable identifiers — less likely to change than visual class names —
which makes them good targets for automation selectors.

**How to find the correct selector:**
1. Open the page in Chrome/Firefox
2. Right-click the Next button → Inspect
3. Look at the element's tag, class, and data attributes in DevTools
4. Pick the most specific combination that uniquely identifies it

---

## Bug 3: Illegal Characters in Screenshot File Path

### The broken code
```python
await page.screenshot(path=f"screenshots/{url}.png")
```

### What goes wrong
`url` is a full URL such as `https://openlibrary.org/works/OL123W/Dune`.
When used directly as a file path this creates:

```
screenshots/https://openlibrary.org/works/OL123W/Dune.png
```

Both `://` and `/` are illegal in file names on Windows and Linux.
The OS raises an error the moment Playwright tries to create the file.

### The fix
```python
import re
slug = re.sub(r"[^\w\-]", "_", url.split("/")[-1])
await page.screenshot(path=f"screenshots/{slug}.png")
```

### Concept: Filename sanitisation

`url.split("/")[-1]` takes only the last segment of the URL path.
For `https://openlibrary.org/works/OL123W/Dune` that gives `"Dune"`.

`re.sub(r"[^\w\-]", "_", ...)` replaces any character that is NOT a word character
(`a-z`, `A-Z`, `0-9`, `_`) or a hyphen with an underscore.

**Pattern breakdown:**
| Part | Meaning |
|---|---|
| `[^\w\-]` | Character class — `^` means NOT, `\w` is any word character, `\-` is a literal hyphen |
| `"_"` | Replace matched characters with an underscore |

Result: `"Dune"` → `"Dune"`, `"OL123W/Dune"` → `"OL123W_Dune"` — safe on all platforms.

---

## Bug 4: Wrong Selector for "Want to Read" Button

### The broken code
```python
await page.click(".want-to-read-btn")
```

### What goes wrong
The class `.want-to-read-btn` does not exist on OpenLibrary book pages.
Playwright's `click()` waits for the selector to appear, hits its timeout, and raises
a `TimeoutError`. Every book in the list fails — nothing is ever added to the reading list.

### The fix
```python
await page.click("button.book-progress-btn.unactivated")
```

### Concept: How to verify a selector before using it

A selector that looks reasonable (`want-to-read-btn`) can simply not exist.
There is no compiler warning for this — it only fails at runtime.

Two ways to verify before committing:
1. **DevTools console** — open the page, press F12, go to Console, type:
   ```js
   document.querySelectorAll(".want-to-read-btn")
   ```
   If it returns an empty NodeList the selector is wrong.

2. **Playwright Inspector** — run with `PWDEBUG=1` to open the inspector and
   use its built-in selector finder.

The correct selector `button.book-progress-btn.unactivated` uses two classes:
- `book-progress-btn` — identifies the shelf button family
- `unactivated` — present only when the book has not been shelved yet

Chaining classes like `.book-progress-btn.unactivated` means the element must have
**both** classes simultaneously — more precise than targeting either one alone.

---

## Bug 5: Missing `await` on Async Method — Silent Wrong Assertion

### The broken code
```python
reading_list = ReadingListPage(page)
actual = reading_list.get_book_count()
assert actual == expected_count
```

### What goes wrong
`get_book_count()` is declared `async def`, which means calling it without `await`
does **not** run the function. Instead Python returns a **coroutine object** —
a description of work that has been scheduled but not yet executed.

`actual` is now something like `<coroutine object get_book_count at 0x...>`.

The assertion `actual == expected_count` compares a coroutine object to an integer.
In Python, different types are never equal, so this is always `False`.
Worse: a coroutine object is truthy, so in some assertion styles the test can silently
pass without ever counting a single book.

Python also emits a `RuntimeWarning: coroutine 'get_book_count' was never awaited`
in the console — easy to miss if you are not watching logs.

### The fix
```python
actual = await reading_list.get_book_count()
```

### Concept: async / await in Python

`async def` marks a function as a coroutine. Coroutines do not run when called —
they return a coroutine object. To actually execute the function and get its return
value you must `await` it.

```python
# This does NOT call the function — it creates a coroutine object
result = some_async_function()

# This RUNS the function and waits for the result
result = await some_async_function()
```

`await` can only be used inside another `async def` function.
In pytest, marking a test with `@pytest.mark.asyncio` makes the test runner handle
the async event loop so that `await` works inside test methods.

**Why async at all?**
Playwright operations (clicking, navigating, reading text) involve waiting for the
browser to respond. Rather than blocking the entire Python thread while waiting,
`async/await` lets Python switch to other tasks in the meantime — making test suites
faster and more scalable.

---

## Summary Table

| Bug | Root cause category | Failure mode | Caught by |
|---|---|---|---|
| 1 — Year parsing crash | Unsafe type conversion | `ValueError` at runtime | First test run |
| 2 — Wrong pagination selector | Wrong CSS selector | Silent under-count | Only on large accounts |
| 3 — Illegal path characters | Missing input sanitisation | `OSError` at runtime | First screenshot attempt |
| 4 — Wrong shelf button selector | Wrong CSS selector | `TimeoutError` at runtime | First add attempt |
| 5 — Missing `await` | Async misuse | Silent wrong assertion | Only if logs are checked |

Bugs 2 and 5 are the most dangerous because they can **silently pass** on small or simple
accounts while failing on real-world data — the hardest category of bug to catch in review.
