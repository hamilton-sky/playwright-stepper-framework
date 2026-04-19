# Exam Requirements — Interviewer Review Guide

Each section is one exam requirement.
For each: **the interviewer question**, the requirement it maps to, and exactly **where in this solution** the answer lives.

---

## 1. Architecture & Code Quality (40%)

### Requirement
Separate POM, flow, and test layers. No raw Playwright calls in tests. OOP with SRP.

---

### Q1: Show me where your Page Object classes are and what each one is responsible for.

**Where in the solution:**
- [poms/openLibrary/pages/book_search_page.py](../poms/openLibrary/pages/book_search_page.py) — search input, result collection, year filtering, pagination
- [poms/openLibrary/pages/book_detail_page.py](../poms/openLibrary/pages/book_detail_page.py) — shelf button (add / remove), book open
- [poms/openLibrary/pages/reading_list_page.py](../poms/openLibrary/pages/reading_list_page.py) — count, pagination, URL collection across both shelves
- [poms/openLibrary/pages/login_page.py](../poms/openLibrary/pages/login_page.py) — login, session detection

Each class owns exactly one page — no class navigates to a different page's elements.

---

### Q2: Where is your flow / orchestration layer? How is it separated from the tests?

**Where in the solution:**
- [exam/flows.py](flows.py) — all four exam functions (`search_books_by_title_under_year`, `add_books_to_reading_list`, `assert_reading_list_count`, `measure_page_performance`) live here
- The `_impl_*` helpers accept `driver` + `settings` and delegate directly to POM methods
- [exam/tests/test_openlibrary_exam.py](tests/test_openlibrary_exam.py) — contains **only** assertions and fixture usage; zero navigation code

**Key design choice:** `flows.py` is the exam-spec public API. Tests call flow functions; flow functions call POMs. Tests never touch POMs directly.

---

### Q3: How do your POMs avoid depending on Playwright directly?

**Where in the solution:**
- [poms/shared/interfaces.py](../poms/shared/interfaces.py) — `IBrowserDriver` and `IElementHandle` abstractions
- [poms/shared/driver.py](../poms/shared/driver.py) — `PlaywrightDriver` wraps Playwright and implements `IBrowserDriver`
- All POM constructors accept `driver: IBrowserDriver`, not a raw Playwright `page`

**Follow-up:** "Why does this matter?" — POMs can be tested with a mock driver; swapping Playwright for another browser library requires changing only `PlaywrightDriver`.

---

### Q4: What base class do your POMs share and what does it give you?

**Where in the solution:**
- [poms/shared/base_page.py](../poms/shared/base_page.py) — `SharedBasePage` with resolver-aware helpers: `_resolve_and_fill_any`, `_resolve_and_click_any`, `_ordered_cfgs`
- [poms/openLibrary/pages/base_page.py](../poms/openLibrary/pages/base_page.py) — site-specific base that inherits `SharedBasePage`

---

## 2. Robustness & Smart Locators (30%)

### Requirement
Pagination across multiple pages. Year filtering. Correct, verified selectors.

---

### Q5: Walk me through your pagination logic for search results.

**Where in the solution:**
- [poms/openLibrary/pages/book_search_page.py](../poms/openLibrary/pages/book_search_page.py) — `collect_books_under_year()` method
- Loop: collect matching items on the current page → if `len(results) < limit` and a next-page element exists → click next → repeat
- Stops when `limit` is reached OR no next-page selector is found

**Bug 2 context:** The exam's starter script used `"a.next-page, a[rel='next']"` — neither exists on OpenLibrary. The fix uses `"a.ChoosePage[data-ol-link-track='Pager|Next']"` verified against the live DOM.

---

### Q6: How do you filter books published before a given year? What could go wrong with a naive implementation?

**Where in the solution:**
- Year extracted via `re.search(r"\b(\d{4})\b", year_text)` in `book_search_page.py`

**Bug 1 context:** The naive `int(year_text.strip())` crashed because `.bookEditions` inner text is `"First published in 1965 — 42 editions"`, not a bare number. The regex safely extracts the 4-digit year.

---

### Q7: How do you handle the reading list spanning multiple pages when counting books?

**Where in the solution:**
- [poms/openLibrary/pages/reading_list_page.py](../poms/openLibrary/pages/reading_list_page.py) — `collect_all_book_urls()` and `_count_shelf()` paginate using the same verified `_NEXT_PAGE_CSS` selector
- `get_book_count()` sums books across both shelves (`want-to-read` + `already-read`)

---

### Q8: How do you locate the "Want to Read" button? What was wrong with the starter script's selector?

**Where in the solution:**
- [poms/openLibrary/pages/book_detail_page.py](../poms/openLibrary/pages/book_detail_page.py) — `add_to_reading_list()` uses `button.book-progress-btn.unactivated`

**Bug 4 context:** The starter used `.want-to-read-btn` — a class that does not exist on the page. Always `TimeoutError`. The fix uses two chained classes that uniquely identify the unshelved button state.

---

## 3. Performance Measurement (15%)

### Requirement
Capture `first_paint_ms`, `dom_content_loaded_ms`, `load_time_ms`. Warn on threshold breach. Write `performance_report.json`.

---

### Q9: Show me your performance measurement implementation. What metrics do you capture and how?

**Where in the solution:**
- [poms/shared/performance.py](../poms/shared/performance.py) — `measure_page_performance()` uses `page.evaluate()` to read `window.performance.timing`
- Metrics: `first_paint_ms`, `dom_content_loaded_ms`, `load_time_ms`
- Threshold breach → `logger.warning(...)`, not a test failure (exam spec says "warn, don't fail")
- Output written to `settings.performance_output` (default: `artifacts/performance_report.json`)

**In tests:**
- [exam/tests/test_openlibrary_exam.py:113-135](tests/test_openlibrary_exam.py#L113-L135) — three performance tests (search page, book detail, reading list)

---

### Q10: Why is a threshold breach a warning and not a test failure?

**Expected answer:** Performance fluctuates with network and machine load. A hard assertion would make the suite flaky in CI. The threshold is a diagnostic signal — it tells you something is slow, but doesn't block the release. Only a sustained regression (tracked over time) warrants a hard failure.

---

## 4. Data-Driven / Config / ENV (10%)

### Requirement
No hardcoded credentials, URLs, or test parameters. Use `.env`, config, and `testdata.json`.

---

### Q11: Where are your credentials stored and how does the framework load them?

**Where in the solution:**
- `.env` file (not committed) — `OPENLIBRARY_USERNAME`, `OPENLIBRARY_PASSWORD`
- [exam/conftest.py:20-35](conftest.py#L20-L35) — `_load_env()` scans three candidate paths for `.env` before importing anything else
- If no credentials and no saved session → auth-dependent tests are **skipped** with a clear message (not silently ignored)

---

### Q12: How do you parametrize tests with different search queries and year filters?

**Where in the solution:**
- `poms/openLibrary/config.py` — `load_test_data()` reads `testdata.json`
- [exam/conftest.py:87-101](conftest.py#L87-L101) — `pytest_generate_tests` feeds `testdata.json` cases into the `test_case` fixture
- CLI flags: `--case N` (run one case by index), `--all-cases` (run all)

---

### Q13: Where is `base_url` defined? Could a tester switch to a staging environment without touching test code?

**Where in the solution:**
- `poms/openLibrary/config.py` — `Settings` dataclass, `base_url` reads from `OPENLIBRARY_BASE_URL` env var with `https://openlibrary.org` as default
- Yes — set `OPENLIBRARY_BASE_URL=https://staging.openlibrary.org` in the env before running

---

## 5. Docs & Support (5%)

### Requirement
README, Allure/HTML report, screenshots, `ReadMeAIBugs.md`.

---

### Q14: Walk me through your bug analysis document. What's in ReadMeAIBugs.md?

**Where in the solution:**
- [exam/ReadMeAIBugs.md](ReadMeAIBugs.md) — five bugs, each with: broken code snippet, exact failure mode, fix, and the underlying concept
- [exam/BugAnalysisExplained.md](BugAnalysisExplained.md) — deeper companion: pattern breakdown tables, DevTools verification steps

---

### Q15: How do screenshots work and when are they taken?

**Where in the solution:**
- `poms/openLibrary/utils/screenshot.py` — `ScreenshotManager.capture()` sanitizes filenames (Bug 3 fix) and saves to `settings.screenshots_dir`
- [exam/flows.py:56-66](flows.py#L56-L66) — screenshot taken after **each** book is added, named `book_{idx}_{slug}.png`
- Screenshot failures are caught and logged as warnings (not test failures) — a missing screenshot should not abort the run

---

### Q16: How do you generate Allure reports?

**Where in the solution:**
- [exam/tests/test_openlibrary_exam.py:36-38](tests/test_openlibrary_exam.py#L36-L38) — `@allure.epic`, `@allure.feature`, `@allure.story` decorators
- Run: `pytest tests/ --alluredir=reports/allure-results && allure serve reports/allure-results`

---

## Bonus — Session Management

### Q17 (bonus): How does your solution avoid logging in on every test?

**Where in the solution:**
- [exam/conftest.py:149-177](conftest.py#L149-L177) — `_authed_storage_state` fixture (session-scoped):
  1. If `artifacts/storage_state.json` exists → load it (instant, no network login)
  2. Else if credentials are set → login once, save cookies to `storage_state.json`
  3. Else → skip auth-dependent tests
- Each per-test `page` fixture creates a fresh browser context but reuses the saved cookies

---

## Silent Bug Radar — The Two Hardest Bugs

These two bugs are designed to separate strong candidates from average ones. Both can **silently pass** on small accounts.

| Bug | Why it's silent | Where the fix lives |
|---|---|---|
| Bug 2 — wrong pagination selector | `query_selector` returns `None`; loop breaks silently; count is correct if all books fit on page 1 | `ReadingListPage._NEXT_PAGE_CSS` and `BookSearchPage` pagination loop |
| Bug 5 — missing `await` | `actual` is a coroutine object (truthy); `assert actual == int` is always `False` but may not raise depending on assertion style | [exam/flows.py:70-81](flows.py#L70-L81) — `actual = await reading_list.get_book_count()` |

A candidate who explains **why** these are dangerous (not just what the fix is) demonstrates senior-level code review depth.
