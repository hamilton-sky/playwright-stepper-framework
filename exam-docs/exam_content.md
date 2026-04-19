# Automation Engineer – OpenLibrary Exam (Full Content)

> Source: Exam PDF (3 pages), captured 3/24/26

---

## About the Exercise

**Target site:** OpenLibrary (`openLibrary.org`)

**Required experience:**
- 4–5 years of hands-on automation
- Python + Playwright
- Allure Reports / HTML / JUnit XML
- **Bonus:** Allure reports, Architecture (POM, OOP, Data-Driven)

---

## Part 1 — Fix the Buggy Functions

The exam provides a starter Python script that uses `async_playwright`.
The candidate must **find and fix the bugs without running the code first** (static analysis).

### Starter Script Structure

```python
class BookSearchPage:
    async def search(page, query):
        # navigates to /search?q=<query>

    async def search_books_by_title_under_year(page, query, max_year, limit=5):
        # paginates results, filters by year, returns list of URLs
        # BUG 1 & BUG 2 live here

async def add_books_to_reading_list(page, urls):
    # visits each URL and clicks "Want to Read"
    # BUG 3 & BUG 4 live here

async def assert_reading_list_count(page, expected_count):
    # navigates to /account/books/want-to-read
    # counts books and asserts
    # BUG 5 lives here

async def measure_page_performance(page, url, threshold_ms=None):
    # measures first_paint_ms, content_loaded_ms, load_time_ms
    # warns if load_time_ms > threshold_ms
    # writes performance_report.json
```

### The 5 Bugs in the Starter Script

| # | Location | Bug |
|---|---|---|
| 1 | `search_books_by_title_under_year` — year extraction | `int(year_text.strip())` crashes; text is `"First published in 1965 — 42 editions"` |
| 2 | Pagination selector constant | `"a.next-page, a[rel='next']"` — neither selector exists on OpenLibrary; loop breaks after page 1 silently |
| 3 | `add_books_to_reading_list` — screenshot | `path=f"screenshots/{url}.png"` — URL contains `://` and `/`, illegal in file paths |
| 4 | `add_books_to_reading_list` — shelf button | `page.click(".want-to-read-btn")` — class does not exist, always TimeoutError |
| 5 | `assert_reading_list_count` | `actual = reading_list.get_book_count()` — missing `await`; `actual` is a coroutine object |

---

## Part 2 — Reading List: Performance Measurement (45 seconds)

Measure performance of the Reading List page (2000 ms threshold):

```python
async def measure_page_performance(page, url, threshold_ms=None):
    first_paint_ms   = ...  # from performance timing
    content_loaded_ms = ...
    load_time_ms     = ...
    if threshold_ms and load_time_ms > threshold_ms:
        print(f"WARNING: load_time_ms={load_time_ms} exceeds threshold {threshold_ms}")
    # save to performance_report.json
```

---

## Full `main()` Flow (Exam Reference)

```python
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL)
        urls = await search_books_by_title_under_year(page, "Dune", 1980, 5)
        await add_books_to_reading_list(page, urls)
        await assert_reading_list_count(page, len(urls))

asyncio.run(main())
```

---

## What to Submit

- GitHub link with access
- `README.md` — architecture, instructions, screenshots
- Report: Allure / HTML / JUnit XML
- `performance_report.json`
- `ReadMeAIBugs.md`

---

## Grading Rubric

| Area | Weight |
|---|---|
| Architecture & code quality (POM, OOP, SRP, Utils) | 40% |
| Robustness & Smart Locators (Pagination, year filter) | 30% |
| Performance (metrics, threshold, JSON report) | 15% |
| Data-Driven (config, ENV, profiles) | 10% |
| Docs/Support (README, Screenshots, Allure) | 5% |
