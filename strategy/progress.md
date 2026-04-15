# Progress Tracker

Updated manually after each change set is completed.
Format: `[x]` = done, `[ ]` = pending, `[~]` = in progress.

---

## P1 — Correctness / Layer Violations

| Status | # | ID | Description | Change Set |
|--------|---|----|-------------|------------|
| [x] | 1 | Q8 | Fix `ScreenshotAction` filename precedence bug | CS-1 |
| [x] | 2 | R9 | Remove hardcoded `#username` from engine layer | CS-1 |
| [x] | 3 | R6 | Dispatch `ExtractDataAction` through factory | CS-1 |

---

## P2 — Fragile / Silent Failures

| Status | # | ID | Description | Change Set |
|--------|---|----|-------------|------------|
| [x] | 4 | Q4 | Document `RunWorkflowAction` temporal coupling | CS-2 |
| [x] | 5 | Q2 | Honour `cfg_browser` at launch | CS-2 |
| [x] | 6 | Q9 | Rename `_resolve_context_vars` | CS-4 |
| [x] | 7 | E3 | Reuse browser across `--data` rows | CS-5 |

---

## P3 — Maintainability / Performance

| Status | # | ID | Description | Change Set |
|--------|---|----|-------------|------------|
| [x] | 8 | R1 | Merge duplicated sub-step dispatch loops | CS-3 |
| [x] | 9 | R4/E6 | Replace JSON round-trip with dict-walk | CS-3 |
| [x] | 10 | Q5 | Extract env-resolution preamble helper | CS-4 |
| [x] | 11 | Q10 | Extract single `_notify` helper | CS-4 |
| [x] | 12 | Q6 | Add `press_enter` opt-out to `FillAction` | CS-4 |
| [x] | 13 | Q12 | Extract `_fetch_attr` helper | CS-4 |
| [x] | 14 | E1 | Move `_load_env()` inside `main()` | CS-5 |
| [x] | 15 | E2 | Build `ElementResolver` once per session | CS-5 |
| [x] | 16 | E5 | Single `mkdir` for `screenshots_dir` | CS-5 |
| [x] | 17 | E8 | Guard `deepcopy` with `{{` token scan | CS-6 |
| [x] | 18 | E9 | Add per-step `skip_screenshot` flag | CS-6 |
| [x] | 19 | R7 | Keep `TestReportReporter` as direct variable | CS-2 |
| [x] | 20 | Q3 | Merge duplicate `test_reporter` guard blocks | CS-2 |

---

## P4 — Polish

| Status | # | ID | Description | Change Set |
|--------|---|----|-------------|------------|
| [x] | 21 | R3 | Use `CONFIDENCE_AUTO` in `is_high_confidence` | CS-7 |
| [x] | 22 | R5 | Hoist `import json` to module level | CS-3 |
| [x] | 23 | Q1 | Remove redundant `cfg_headless` variable | CS-2 |
| [x] | 24 | Q7 | Remove dead `if step.extra else None` guards | CS-4 |
| [x] | 25 | Q11 | Fix `ExecutionContext` docstring | CS-7 |
| [x] | 26 | Q13 | Add `TypeVar` to `GlueAction._build_pom` | CS-7 |
| [x] | 27 | R2 | Deduplicate `allure serve` call | CS-2 |
| [x] | 28 | R8 | Adopt `python-dotenv` | CS-7 |
| [x] | 29 | E4 | Guard `storage_state` write | CS-6 |
| [x] | 30 | E7 | Move `mkdir` to `MeasurePerformanceAction.__init__` | CS-6 |
| [ ] | 31 | E10 | Batch attribute extraction | CS-6 |

---

## Change Set Summary

| Change Set | Items | Status | Notes |
|------------|-------|--------|-------|
| CS-1 — P1 fixes | Q8, R6, R9 | [x] | Completed 2026-04-15 |
| CS-2 — main.py cleanup | Q4, Q2, R7, Q3, Q1, R2 | [x] | Completed 2026-04-15 |
| CS-3 — Sub-step loop merge | R1, R4/E6, R5 | [x] | Completed 2026-04-15 |
| CS-4 — strategies.py quality | Q5, Q10, Q12, Q6, Q7, Q9 | [x] | Completed 2026-04-15 |
| CS-5 — Data-mode performance | E3, E1, E2, E5 | [x] | Completed 2026-04-15 |
| CS-6 — Runtime efficiency | E8, E9, E7, E4, E10 | [~] | E8, E9, E7, E4 done 2026-04-15. E10 (batch attr extraction) deferred to CS-7. |
| CS-7 — Polish | R3, R8, Q11, Q13 | [x] | Completed 2026-04-15 |

---

## Notes / Decisions Log

_Record any decisions made during implementation here._

| Date | Note |
|------|------|
| 2026-04-15 | CS-1 complete. FIX 1: removed dead `if step.extra` guard in `ScreenshotAction`. FIX 2: `EnsureLoginAction` wait is now opt-in via `form_ready_selector` in `step.extra`. FIX 3: added `__init__(action_factory)` to `PaginateAction`; sub-extract now goes through `factory.create` + `action.execute` so hooks/observers fire correctly. |
