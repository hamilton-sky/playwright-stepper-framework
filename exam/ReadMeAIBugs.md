# ReadMeAIBugs.md — Static Bug Analysis

Analysis of the starter script provided in the exam instructions.
Each bug is identified **without running the code** — purely from reading the source.

---

## Bug 1: Year Parsing Crashes on Real DOM Text

**Location:** `search_books_by_title_under_year` → year extraction loop

```python
year_el = await item.query_selector(".bookEditions")
if year_el:
    year_text = await year_el.inner_text()
    year = int(year_text.strip())
```

**Problem:**  
`inner_text()` on `.bookEditions` returns a string like `"First published in 1965 — 42 editions"`,
not a bare number. Calling `int()` on this string raises a `ValueError` and crashes the entire
search loop — no books are ever collected.

**Fix:**  
Extract the 4-digit year with a regex:
```python
import re
match = re.search(r"\b(\d{4})\b", year_text)
if match:
    year = int(match.group(1))
```

---

## Bug 2: Typo in CSS Selector — `.searchResultITem` (Capital T)

**Location:** `search_books_by_title_under_year` → result collection loop

```python
results = await page.query_selector_all(".searchResultITem")
```

**Problem:**  
The selector has a capital `T` in `ITem`. The actual OpenLibrary class is `.searchResultItem` (lowercase `t`).
`query_selector_all` returns an empty list silently, so the function never finds any results
and returns `[]` on every search.

**Fix:**  
```python
results = await page.query_selector_all(".searchResultItem")
```

---

## Bug 3: Illegal Characters in Screenshot File Path

**Location:** `add_books_to_reading_list`

```python
await page.screenshot(path=f"screenshots/{url}.png")
```

**Problem:**  
`url` is a full URL like `https://openlibrary.org/works/OL123W/Dune`.
This contains `://` and `/` characters that are **illegal in file paths** on both Windows and Linux.
Playwright raises an OS error when attempting to save the file.

**Fix:**  
Sanitize the URL before using it as a filename:
```python
import re
slug = re.sub(r"[^\w\-]", "_", url.split("/")[-1])
await page.screenshot(path=f"screenshots/{slug}.png")
```

---

## Bug 4: Wrong Selector for "Want to Read" Button

**Location:** `add_books_to_reading_list`

```python
await page.click(".want-to-read-btn")
```

**Problem:**  
The class `.want-to-read-btn` does not exist on OpenLibrary's book pages.
The actual shelf button uses `button.book-progress-btn.unactivated` or
`button.book-progress-btn.primary-action`. This click always times out.

**Fix:**  
```python
await page.click("button.book-progress-btn.unactivated")
```

---

## Bug 5: Missing `await` on Async Method — Silent Wrong Assertion

**Location:** `assert_reading_list_count`

```python
reading_list = ReadingListPage(page)
actual = reading_list.get_book_count()
assert actual == expected_count
```

**Problem:**  
`get_book_count()` is an `async def` method. Without `await`, `actual` receives a **coroutine object**
instead of an integer. The `assert` then compares `<coroutine>` to an `int`, which is always `False` —
but because `actual` is a truthy coroutine object, the comparison `actual == expected_count` simply
returns `False` without raising `AssertionError` in some contexts. At minimum the assertion is testing
the wrong thing; at worst it silently passes.

**Fix:**  
```python
actual = await reading_list.get_book_count()
```
