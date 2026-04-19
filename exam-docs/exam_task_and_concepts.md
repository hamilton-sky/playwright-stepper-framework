# Exam Task & Concepts — Automation Engineer (OpenLibrary)

---

## What Is the Task?

Build a complete end-to-end automation solution for [OpenLibrary](https://openlibrary.org) using Python + Playwright.

The exam gives you a **broken starter script** and asks you to:
1. **Find and fix 5 bugs** by reading the code (no running it first).
2. **Extend the script** into a clean, production-grade automation framework.
3. **Prove quality** with reports, screenshots, performance metrics, and documentation.

The full flow the exam expects:
```
Search "Dune" → filter books published before 1980 → collect up to 5 URLs
→ Add each to reading list → screenshot each → assert count → measure performance
```

---

## The 5 Core Concepts Being Tested

### 1. Static Bug Analysis (reading broken code)
The exam gives you working-looking code with 5 subtle bugs. You must identify each bug, explain why it breaks, and fix it — **without running the code**. This tests code review skills, Python knowledge, and async awareness.

Key sub-skills tested:
- Recognising unsafe type conversions (`int(arbitrary_string)`)
- Spotting **silent failures** (wrong CSS selector that returns `None` instead of raising)
- Understanding Python `async/await` — calling async without `await` gives you a coroutine object, not a value
- File-system awareness — what characters are legal in a file path

### 2. POM Architecture (Page Object Model)
The solution must not be a monolithic script. Each page must be its own class with all selectors isolated inside it. This is the highest-weighted criterion (40%).

Expected structure:
```
BookSearchPage   — search input, result items, year text, next-page button
BookDetailPage   — shelf button (add / remove)
ReadingListPage  — book count, pagination, URL collection
```

Principles tested:
- **Single Responsibility**: each class owns exactly one page
- **OOP**: inheritance, encapsulation of selectors
- **Dependency Inversion**: pages accept a driver/interface, not raw Playwright directly

### 3. Pagination & Robust Locators (30%)
The search results and reading list can span multiple pages. The candidate must:
- Loop across pages until `limit` books are collected or no next-page exists
- Use **correct, verified CSS selectors** — not guessed ones
- Prefer stable selectors (data attributes) over fragile class names

The pagination bug (Bug 2) is specifically designed to catch candidates who copy-paste selectors without verifying them against the actual DOM.

### 4. Performance Measurement (15%)
The solution must capture browser navigation timing metrics and write them to `performance_report.json`:
- `first_paint_ms`
- `dom_content_loaded_ms`
- `load_time_ms`

A `threshold_ms` parameter triggers a warning (not a test failure) when load time is too slow. This tests understanding of browser performance APIs and the difference between a **warning** and an **assertion**.

### 5. Data-Driven / Config / ENV (10%)
Credentials, base URL, delays, and test parameters must not be hardcoded. Expected:
- `.env` file for secrets (username, password)
- `config.py` / `settings.py` for constants
- `testdata.json` for parametrized test cases (query, max_year, limit)

---

## What the Graders Are Really Looking For

### Architecture (the make-or-break criterion — 40%)
A passing solution has clearly separated concerns:
- Selectors in POM classes (not in test functions)
- Flow logic in a flow/orchestration layer (not inside POM methods)
- Tests assert outcomes, they don't navigate

A failing solution stuffs everything into `main()` or test functions.

### Silent Bug Awareness
Bugs 2 and 5 are designed to test whether the candidate understands **silent failures**:
- Bug 2 (wrong pagination selector): tests pass on small accounts, fail mysteriously on large ones
- Bug 5 (missing `await`): assertion runs against a coroutine object — may silently pass

Candidates who only find the loudly crashing bugs (1, 3, 4) show less depth than those who also find the silent ones.

### Async/Await Mastery
Playwright is fully async. Every Playwright call (`click`, `fill`, `inner_text`, `screenshot`) must be awaited. Missing a single `await` produces a coroutine object — not an error, just a wrong value. The exam includes one missing `await` specifically to test whether the candidate understands this.

### Locator Strategy
The exam expects the candidate to:
- Verify selectors against the real DOM (DevTools or Playwright Inspector)
- Prefer semantic locators (`get_by_role`, `get_by_label`) over brittle CSS class names
- Understand that `data-*` attributes are more stable than visual class names

### Documentation & Reporting
Even though docs/support is only 5%, the README + Allure report + screenshots signal whether the candidate treats automation as engineering (not just scripting).

---

## Candidate Competency Map

| What they submit | What it reveals |
|---|---|
| Monolithic script, no POM | Junior — hasn't internalized separation of concerns |
| POM classes but no data-driven layer | Mid-level — architecture present, config/env awareness missing |
| All 5 bugs found including the silent ones | Strong — code review depth, async mastery |
| Only bugs 1, 3, 4 found | Average — catches crashes, misses silent failures |
| `>=` assertion vs `==` with clean reasoning | Senior — understands test isolation and parallelism |
| Allure + screenshots + `performance_report.json` | Completes the full spec, not just the code |
