# Implementation Plan

Ordered from most to least important. Each item links to its finding and solution.

**Priority tiers:**
- **P1 — Fix Now**: Correctness bugs and layer violations. Must be addressed before any new features.
- **P2 — Fix Soon**: Fragile code and silent failures that will hurt in production.
- **P3 — Fix When Convenient**: Maintainability and performance improvements.
- **P4 — Polish**: Low-risk cleanup with minimal impact.

---

## P1 — Fix Now (Correctness / Layer Violations)

| # | ID | What | File(s) | Finding | Solution |
|---|----|------|---------|---------|----------|
| 1 | Q8 | Fix `ScreenshotAction` filename precedence bug | [strategies.py:237](../stepper/engine/actions/strategies.py#L237) | [Q8](findings.md#q8) | [S-Q8](solutions.md#s-q8) |
| 2 | R9 | Remove hardcoded `#username` from generic engine | [strategies.py:470](../stepper/engine/actions/strategies.py#L470) | [R9](findings.md#r9) | [S-R9](solutions.md#s-r9) |
| 3 | R6 | Dispatch `ExtractDataAction` through factory in `PaginateAction` | [strategies.py:762](../stepper/engine/actions/strategies.py#L762) | [R6](findings.md#r6) | [S-R6](solutions.md#s-r6) |

---

## P2 — Fix Soon (Fragile / Silent Failures)

| # | ID | What | File(s) | Finding | Solution |
|---|----|------|---------|---------|----------|
| 4 | Q4 | Document / fix `RunWorkflowAction` temporal coupling | [main.py:203](../stepper/main.py#L203) | [Q4](findings.md#q4) | [S-Q4](solutions.md#s-q4) |
| 5 | Q2 | Honour `cfg_browser` setting when launching browser | [main.py:141](../stepper/main.py#L141) | [Q2](findings.md#q2) | [S-Q2](solutions.md#s-q2) |
| 6 | Q9 | Rename `_resolve_context_vars` — name misleads callers | [step_runner.py:169](../stepper/engine/runner/step_runner.py#L169) | [Q9](findings.md#q9) | [S-Q9](solutions.md#s-q9) |
| 7 | E3 | Reuse browser across `--data` rows | [main.py:263](../stepper/main.py#L263) | [E3](findings.md#e3) | [S-E3](solutions.md#s-e3) |

---

## P3 — Fix When Convenient (Maintainability / Performance)

| # | ID | What | File(s) | Finding | Solution |
|---|----|------|---------|---------|----------|
| 8 | R1 | Merge duplicated sub-step dispatch loops | [strategies.py:361](../stepper/engine/actions/strategies.py#L361), [strategies.py:474](../stepper/engine/actions/strategies.py#L474) | [R1](findings.md#r1) | [S-R1](solutions.md#s-r1) |
| 9 | R4 / E6 | Replace JSON round-trip with dict-walk substitution | [strategies.py:372](../stepper/engine/actions/strategies.py#L372), [strategies.py:475](../stepper/engine/actions/strategies.py#L475) | [R4](findings.md#r4), [E6](findings.md#e6) | [S-R4](solutions.md#s-r4) |
| 10 | Q5 | Extract env-resolution preamble helper | [strategies.py:72](../stepper/engine/actions/strategies.py#L72), [strategies.py:122](../stepper/engine/actions/strategies.py#L122) | [Q5](findings.md#q5) | [S-Q5](solutions.md#s-q5) |
| 11 | Q10 | Extract single `_notify` helper in `StepRunner` | [step_runner.py:145](../stepper/engine/runner/step_runner.py#L145) | [Q10](findings.md#q10) | [S-Q10](solutions.md#s-q10) |
| 12 | Q6 | Add `press_enter` opt-out to `FillAction` | [strategies.py:138](../stepper/engine/actions/strategies.py#L138) | [Q6](findings.md#q6) | [S-Q6](solutions.md#s-q6) |
| 13 | Q12 | Extract `_fetch_attr` helper in `ExtractDataAction` | [strategies.py:629](../stepper/engine/actions/strategies.py#L629) | [Q12](findings.md#q12) | [S-Q12](solutions.md#s-q12) |
| 14 | E1 | Move `_load_env()` inside `main()` | [main.py:41](../stepper/main.py#L41) | [E1](findings.md#e1) | [S-E1](solutions.md#s-e1) |
| 15 | E2 | Build `ElementResolver` once outside the run loop | [main.py:117](../stepper/main.py#L117) | [E2](findings.md#e2) | [S-E2](solutions.md#s-e2) |
| 16 | E5 | Single `mkdir` for `screenshots_dir` | [main.py:164](../stepper/main.py#L164), [strategies.py:232](../stepper/engine/actions/strategies.py#L232), [step_runner.py:54](../stepper/engine/runner/step_runner.py#L54) | [E5](findings.md#e5) | [S-E5](solutions.md#s-e5) |
| 17 | E8 | Guard `deepcopy` with `{{` token scan | [step_runner.py:198](../stepper/engine/runner/step_runner.py#L198) | [E8](findings.md#e8) | [S-E8](solutions.md#s-e8) |
| 18 | E9 | Add per-step `skip_screenshot` flag | [step_runner.py:117](../stepper/engine/runner/step_runner.py#L117) | [E9](findings.md#e9) | [S-E9](solutions.md#s-e9) |
| 19 | R7 | Keep `TestReportReporter` as direct variable | [main.py:145](../stepper/main.py#L145) | [R7](findings.md#r7) | [S-R7](solutions.md#s-r7) |
| 20 | Q3 | Merge duplicate `test_reporter` guard blocks | [main.py:150](../stepper/main.py#L150) | [Q3](findings.md#q3) | [S-Q3](solutions.md#s-q3) |

---

## P4 — Polish (Low Risk, Low Impact)

| # | ID | What | File(s) | Finding | Solution |
|---|----|------|---------|---------|----------|
| 21 | R3 | Use `CONFIDENCE_AUTO` constant in `is_high_confidence` | [interfaces.py:67](../stepper/engine/interfaces.py#L67) | [R3](findings.md#r3) | [S-R3](solutions.md#s-r3) |
| 22 | R5 | Hoist `import json` to module level in `strategies.py` | [strategies.py:349](../stepper/engine/actions/strategies.py#L349), [strategies.py:473](../stepper/engine/actions/strategies.py#L473) | [R5](findings.md#r5) | [S-R5](solutions.md#s-r5) |
| 23 | Q1 | Remove redundant `cfg_headless` variable | [main.py:103](../stepper/main.py#L103) | [Q1](findings.md#q1) | [S-Q1](solutions.md#s-q1) |
| 24 | Q7 | Remove dead `if step.extra else None` guards | [strategies.py:200](../stepper/engine/actions/strategies.py#L200) | [Q7](findings.md#q7) | [S-Q7](solutions.md#s-q7) |
| 25 | Q11 | Fix `ExecutionContext` docstring for `collected_books` | [interfaces.py:101](../stepper/engine/interfaces.py#L101) | [Q11](findings.md#q11) | [S-Q11](solutions.md#s-q11) |
| 26 | Q13 | Add `TypeVar` typing to `GlueAction._build_pom` | [glue_action.py:51](../stepper/engine/pages/glue_action.py#L51) | [Q13](findings.md#q13) | [S-Q13](solutions.md#s-q13) |
| 27 | R2 | Deduplicate `allure serve` subprocess call | [main.py:223](../stepper/main.py#L223), [main.py:276](../stepper/main.py#L276) | [R2](findings.md#r2) | [S-R2](solutions.md#s-r2) |
| 28 | R8 | Adopt `python-dotenv` or document parser limitations | [main.py:21](../stepper/main.py#L21) | [R8](findings.md#r8) | [S-R8](solutions.md#s-r8) |
| 29 | E4 | Guard `storage_state` write with a dirty flag | [main.py:214](../stepper/main.py#L214) | [E4](findings.md#e4) | [S-E4](solutions.md#s-e4) |
| 30 | E7 | Move `mkdir` to `MeasurePerformanceAction.__init__` | [strategies.py:534](../stepper/engine/actions/strategies.py#L534) | [E7](findings.md#e7) | [S-E7](solutions.md#s-e7) |
| 31 | E10 | Batch attribute extraction in `ExtractDataAction` | [strategies.py:627](../stepper/engine/actions/strategies.py#L627) | [E10](findings.md#e10) | [S-E10](solutions.md#s-e10) |

---

## Natural groupings for implementation

The items above cluster into 7 focused change sets that can each be done in one conversation:

| Change Set | Items | Description |
|------------|-------|-------------|
| **CS-1** | Q8, R6, R9 | P1 fixes — correctness bugs and layer violations |
| **CS-2** | Q4, Q2, Q9, R7, Q3, Q1, R2 | main.py cleanup and structural clarity |
| **CS-3** | R1, R4/E6, R5 | Merge sub-step loops + remove JSON round-trips |
| **CS-4** | Q5, Q10, Q12, Q6, Q7 | strategies.py and step_runner.py quality fixes |
| **CS-5** | E3, E1, E2, E5 | --data mode performance + import time optimisation |
| **CS-6** | E8, E9, E7, E4, E10 | Runtime efficiency improvements |
| **CS-7** | R3, R8, Q11, Q13 | Constants, docstrings, typing polish |

See [conversation_prompts.md](conversation_prompts.md) for ready-to-use prompts for each change set.
