# Findings — Issues & Improvements

Each finding has an ID, category, severity, the affected file+line, and a pointer to its solution in [solutions.md](solutions.md).

Severity scale: **Critical** (correctness bug) → **High** (layer violation / fragile) → **Medium** (maintainability) → **Low** (polish)

---

## Reuse Issues (R)

| ID | Severity | File : Line | Description | Solution |
|----|----------|-------------|-------------|----------|
| R1 | Medium | [strategies.py:361–410](../stepper/engine/actions/strategies.py#L361) & [strategies.py:474–488](../stepper/engine/actions/strategies.py#L474) | Sub-step dispatch loop duplicated in `ForEachItemAction` and `EnsureLoginAction`. Both iterate raw step dicts, JSON-round-trip substitute, call `_dict_to_step_config`, then `action.execute()`. | [S-R1](solutions.md#s-r1) |
| R2 | Low | [main.py:223](../stepper/main.py#L223) & [main.py:276](../stepper/main.py#L276) | `subprocess.run(["allure", "serve", ...])` copy-pasted verbatim in both single-run and `--data` branches. | [S-R2](solutions.md#s-r2) |
| R3 | Low | [interfaces.py:67](../stepper/engine/interfaces.py#L67) | `ResolveResult.is_high_confidence` hardcodes `0.80` — `CONFIDENCE_AUTO` constant is imported on line 26 of the same file. | [S-R3](solutions.md#s-r3) |
| R4 | Medium | [strategies.py:372–388](../stepper/engine/actions/strategies.py#L372) & [strategies.py:475–476](../stepper/engine/actions/strategies.py#L475) | `json.dumps → .replace → json.loads` template substitution hand-rolled in two actions. `EnsureLoginAction`'s version is a no-op round-trip (dict → string → dict with no substitutions). | [S-R4](solutions.md#s-r4) |
| R5 | Low | [strategies.py:349](../stepper/engine/actions/strategies.py#L349) & [strategies.py:473](../stepper/engine/actions/strategies.py#L473) | `import json` buried inside two separate method bodies instead of a single top-level import. | [S-R5](solutions.md#s-r5) |
| R6 | High | [strategies.py:762](../stepper/engine/actions/strategies.py#L762) | `PaginateAction` instantiates `ExtractDataAction()` directly, bypassing the `ActionFactory` and `execute()` template method (pre/post hooks, observer notification all skipped). | [S-R6](solutions.md#s-r6) |
| R7 | Low | [main.py:145](../stepper/main.py#L145) | `TestReportReporter` found by scanning `reporters` list with `next(isinstance(...))` three lines after being constructed. Should be kept as a direct local variable. | [S-R7](solutions.md#s-r7) |
| R8 | Low | [main.py:21–38](../stepper/main.py#L21) | `_load_env()` re-implements `python-dotenv` (17 lines). Silently mis-handles quoted values and multi-line values. | [S-R8](solutions.md#s-r8) |
| R9 | High | [strategies.py:470](../stepper/engine/actions/strategies.py#L470) | `EnsureLoginAction` hardcodes `#username` CSS selector in the generic engine layer — an OpenLibrary-specific selector that bypasses the resolver cascade. | [S-R9](solutions.md#s-r9) |

---

## Quality Issues (Q)

| ID | Severity | File : Line | Description | Solution |
|----|----------|-------------|-------------|----------|
| Q1 | Low | [main.py:103](../stepper/main.py#L103) & [main.py:109](../stepper/main.py#L109) | `cfg_headless = not headless` is computed identically in both the `try` and `except` blocks — same value either way, redundant variable. | [S-Q1](solutions.md#s-q1) |
| Q2 | Medium | [main.py:102](../stepper/main.py#L102) & [main.py:141](../stepper/main.py#L141) | `cfg_browser = settings.browser` is loaded but `pw.chromium.launch()` is always called — non-Chromium browser config is silently ignored. | [S-Q2](solutions.md#s-q2) |
| Q3 | Low | [main.py:150–164](../stepper/main.py#L150) | Same `if test_reporter and test_reporter.manager.current_test_dir:` guard evaluated twice in a row (log handler block, then screenshots block). Can be merged into one `if`. | [S-Q3](solutions.md#s-q3) |
| Q4 | High | [main.py:203–205](../stepper/main.py#L203) | `RunWorkflowAction` must be registered *after* `StepRunner` is created because it captures `runner.run`. This ordering dependency is invisible; moving the lines breaks sub-flow dispatch silently. | [S-Q4](solutions.md#s-q4) |
| Q5 | Medium | [strategies.py:72–78](../stepper/engine/actions/strategies.py#L72) & [strategies.py:122–128](../stepper/engine/actions/strategies.py#L122) | Env-resolution preamble (4-line `_resolve_input_value` + early-return block) copy-pasted into `ClickAction` and `FillAction`. | [S-Q5](solutions.md#s-q5) |
| Q6 | Medium | [strategies.py:138](../stepper/engine/actions/strategies.py#L138) | `FillAction` unconditionally presses Enter after every fill. No way to fill without submitting (e.g. multi-field forms). | [S-Q6](solutions.md#s-q6) |
| Q7 | Low | [strategies.py:200–201](../stepper/engine/actions/strategies.py#L200) | `step.extra.get("label") if step.extra else None` — `StepConfig.extra` is always a `dict` (default_factory), so `.get()` is always safe. Guard is dead code. | [S-Q7](solutions.md#s-q7) |
| Q8 | Critical | [strategies.py:237](../stepper/engine/actions/strategies.py#L237) | `ScreenshotAction` filename expression has a Python operator-precedence bug. The ternary binds to the `or`'s right side, making the `if step.extra` guard dead — both branches produce the same fallback string. | [S-Q8](solutions.md#s-q8) |
| Q9 | Low | [step_runner.py:169](../stepper/engine/runner/step_runner.py#L169) | `_resolve_context_vars` only substitutes from `ctx.counts` but the name implies full context resolution. Callers with `collected_items` / `extracted_data` templates get silent no-ops. | [S-Q9](solutions.md#s-q9) |
| Q10 | Medium | [step_runner.py:145–164](../stepper/engine/runner/step_runner.py#L145) | Three observer-notify methods (`_notify_start`, `_notify_done`, `_notify_log`) share identical `for obs / try / except: pass` structure — copy-pasted three times. | [S-Q10](solutions.md#s-q10) |
| Q11 | Low | [interfaces.py:101](../stepper/engine/interfaces.py#L101) | `ExecutionContext` docstring claims `collected_books` is a backward-compat alias field — it is not a field; the alias lives in `ForEachItemAction` as a `getattr(page, ...)`. Misleading. | [S-Q11](solutions.md#s-q11) |
| Q12 | Medium | [strategies.py:629–652](../stepper/engine/actions/strategies.py#L629) | `ExtractDataAction` attr-fetching switch (`innerText`/`innerHTML`/`textContent`/generic) written out twice — once for single-attr scalar, once for multi-attr dict case. | [S-Q12](solutions.md#s-q12) |
| Q13 | Low | [glue_action.py:51](../stepper/engine/pages/glue_action.py#L51) | `GlueAction._build_pom` accepts `pom_cls` as untyped `Any` — IDEs and mypy cannot verify return type. Convention enforcement with no tooling support. | [S-Q13](solutions.md#s-q13) |

---

## Efficiency Issues (E)

| ID | Severity | File : Line | Description | Solution |
|----|----------|-------------|-------------|----------|
| E1 | Medium | [main.py:41](../stepper/main.py#L41) | `_load_env()` called at module scope — any test that imports `run` triggers a filesystem read at import time. | [S-E1](solutions.md#s-e1) |
| E2 | Medium | [main.py:117–122](../stepper/main.py#L117) | `ElementResolver` (and potentially the MiniLM embedding model) rebuilt on every `run()` call. In `--data` mode = one full rebuild per row. | [S-E2](solutions.md#s-e2) |
| E3 | High | [main.py:263–273](../stepper/main.py#L263) | `--data` mode: `asyncio.run(run(...))` per row = N browser launches, N context setups, N resolver builds. No reuse across rows. | [S-E3](solutions.md#s-e3) |
| E4 | Low | [main.py:214–216](../stepper/main.py#L214) | `context.storage_state(path=...)` written at end of every run even when session state did not change. Unnecessary Playwright API call + file write. | [S-E4](solutions.md#s-e4) |
| E5 | Low | [main.py:164](../stepper/main.py#L164), [strategies.py:232](../stepper/engine/actions/strategies.py#L232), [step_runner.py:54](../stepper/engine/runner/step_runner.py#L54) | Same `screenshots_dir` directory `mkdir`-ed three times per run from three different callsites. | [S-E5](solutions.md#s-e5) |
| E6 | Medium | [strategies.py:373–389](../stepper/engine/actions/strategies.py#L373) | `ForEachItemAction` does `json.dumps + .replace + json.loads` for every `(item, sub_step)` pair — O(items × sub_steps) unnecessary serialisation. | [S-E6](solutions.md#s-e6) |
| E7 | Low | [strategies.py:534](../stepper/engine/actions/strategies.py#L534) | `MeasurePerformanceAction` calls `output_path.parent.mkdir()` on every invocation. The output directory is stable after the first call. | [S-E7](solutions.md#s-e7) |
| E8 | Medium | [step_runner.py:198](../stepper/engine/runner/step_runner.py#L198) | `copy.deepcopy(step.extra)` called on every step once `ctx.counts` is non-empty, even when `extra` contains no `{{` tokens. | [S-E8](solutions.md#s-e8) |
| E9 | Medium | [step_runner.py:117–124](../stepper/engine/runner/step_runner.py#L117) | Auto-screenshot after every step, no per-step opt-out. For long workflows: N full PNG captures blocking the event loop. | [S-E9](solutions.md#s-e9) |
| E10 | Low | [strategies.py:627–652](../stepper/engine/actions/strategies.py#L627) | `ExtractDataAction` fetches attributes sequentially per element — N_locators × N_attrs async round-trips. `locator.evaluate_all` could batch into one JS call. | [S-E10](solutions.md#s-e10) |
