# Explanations — Why Each Issue Matters and What the Fix Gains

---

## CS-1 — P1 Correctness Fixes

### Q8 — ScreenshotAction filename precedence bug

**What is wrong:** Python's operator precedence causes:
```python
name = step.extra.get("filename") or f"{ts}_step.png" if step.extra else f"{ts}_step.png"
```
to be parsed as:
```python
name = step.extra.get("filename") or (f"{ts}_step.png" if step.extra else f"{ts}_step.png")
```
Both branches of the ternary produce the same string, so `step.extra.get("filename")` is always used when `extra` is a non-empty dict — but if `step.extra` is an empty dict (falsy), the `or` falls to the ternary, which also falls to the same default. Concretely: **a workflow step that sets `"extra": {"filename": "my_shot.png"}` will correctly use `my_shot.png`, but the guard is misleading and the code is fragile.**

**What the fix gives:** Correct, readable filename selection. One line, no ambiguity.

---

### R9 — Hardcoded `#username` in the engine layer

**What is wrong:** `EnsureLoginAction` is in `stepper/engine/actions/strategies.py` — the generic engine that knows nothing about any specific site. It contains:
```python
await page.wait_for_selector("#username", state="visible", timeout=10_000)
```
`#username` is an OpenLibrary-specific DOM selector. This means:
1. The engine imports site knowledge — layer contract violated.
2. Running `EnsureLoginAction` on SauceDemo or phpTravels will wait 10 s for an element that doesn't exist, then silently continue.

**What the fix gives:** The selector comes from `step.extra.get("form_ready_selector")`. The engine stays generic. Site-specific details stay in glue. No silent 10-second waits on the wrong site.

---

### R6 — PaginateAction bypasses ActionFactory

**What is wrong:**
```python
await ExtractDataAction()._execute(page, extract_step, resolver, context)
```
- Calls `_execute` directly, skipping the `execute()` template method.
- This means `pre_execute()` and `post_execute()` hooks are never called.
- Observer notification (logging, reporting) is skipped for every extract sub-step inside pagination.
- Constructs a new `ExtractDataAction()` on every page — if its `__init__` ever gains parameters, `PaginateAction` silently breaks.

**What the fix gives:** Sub-steps inside pagination are treated identically to top-level steps — hooks fire, observers are notified, the factory resolves the instance. Zero special-casing.

---

## CS-2 — main.py Cleanup

### Q2 — cfg_browser is ignored

**What is wrong:** The settings system supports `browser: chromium | firefox | webkit`, but `main.py` always calls `pw.chromium.launch()`. Setting `browser: firefox` in config silently does nothing. The label is forwarded to the test reporter (so the HTML report says "firefox") but the actual browser is always Chromium.

**What the fix gives:** The browser the user configured is the browser that actually runs. The test report label matches reality.

---

### Q4 — RunWorkflowAction temporal coupling

**What is wrong:** `RunWorkflowAction` must be registered *after* `StepRunner` is created because it closes over `runner.run`. The ordering is invisible in the code — move those three lines above the `StepRunner(...)` constructor and sub-flow dispatch silently stops working (the closure captures `runner` before it's bound).

**What the fix gives:** The constraint is documented at the call site, so future developers don't accidentally reorder these lines. The longer-term fix (lazy injection) removes the constraint entirely.

---

## CS-3 — Sub-step Loop Merge + JSON Round-trip Removal

### R4 / E6 — JSON round-trip for template substitution

**What is wrong:** To substitute `{{item_url}}` into a step dict, the code:
1. Converts the dict to a JSON string (`json.dumps`)
2. Does string `.replace()` on the result
3. Parses the string back to a dict (`json.loads`)

Problems:
- Unnecessary serialisation cost, repeated for every `(item, sub_step)` pair — O(N×M) codec overhead.
- `EnsureLoginAction`'s version has no substitutions at all — it's a pure no-op round-trip (makes a deep copy by accident).
- A value containing a `"` quote character will corrupt the JSON and raise an error.

**What the fix gives:** A recursive dict-walk substitution (`_apply_substitutions`) that is faster, handles all value types correctly, and cannot produce malformed JSON.

---

### R1 — Duplicated sub-step dispatch loop

**What is wrong:** `ForEachItemAction` and `EnsureLoginAction` both contain their own version of:
```
for raw in steps_raw:
    json-round-trip the dict
    _dict_to_step_config(...)
    action.execute(...)
```
They differ in two details: the substitution tokens and whether to stop on first failure. Any bug fix or enhancement to one loop must be manually applied to the other.

**What the fix gives:** One `_run_sub_steps()` function. Bug fixes propagate automatically. The two action classes state their intent clearly through their arguments rather than through copied code.

---

## CS-4 — strategies.py and step_runner.py Quality Fixes

### Q5 — Copy-pasted env-resolution preamble

**What is wrong:** `ClickAction` and `FillAction` both start with the same 4-line block:
```python
value, was_env = _resolve_input_value(step.input_value)
if was_env and not value:
    return StepResult(step=step, status="failed", error=...)
```
If the error message or logic changes, both must be updated. If a third action needs env resolution, it copies the block again.

**What the fix gives:** One `_checked_input_value()` helper. All actions that need env-variable input call it and early-return on the failure case. The preamble exists once.

---

### Q6 — FillAction unconditional Enter press

**What is wrong:** `FillAction` always does `await result.locator.press("Enter")` after filling. This works for single-field search forms. It fails for multi-field forms where pressing Enter after each field submits the form prematurely (e.g. a checkout page with First Name, Last Name, Address, City).

**What the fix gives:** Workflows opt in to Enter submission (`"press_enter": true`) or out (`"press_enter": false`). Default remains `true` for backward compatibility. Multi-field forms now work correctly.

---

### Q10 — Three identical observer-notify methods

**What is wrong:** `_notify_start`, `_notify_done`, and `_notify_log` all contain:
```python
for obs in self._observers:
    try:
        obs.on_XXX(...)
    except Exception:
        pass
```
The `except Exception: pass` is a significant decision (observers must never crash the runner). It is made in three places, meaning it could be inconsistently changed in the future.

**What the fix gives:** The swallow-all decision is made once in `_notify()`. Adding a fourth observer event type (e.g. `on_suite_start`) requires one line, not a copy-pasted block.

---

## CS-5 — Data-mode Performance

### E1 — `_load_env()` at module import time

**What is wrong:** `_load_env()` is called at the top level of `main.py` (line 41). Any test file that does `from stepper.main import run` triggers a filesystem `stat` + file read of `.env` at import time — before any test has run.

**What the fix gives:** `_load_env()` is called inside `main()`, so it only fires when the CLI entrypoint is actually invoked. Test imports are free of side-effects.

---

### E2 — ElementResolver rebuilt per run() call

**What is wrong:** `DefaultResolverFactory().build_cascade()` and `ElementResolver(...)` are constructed inside `run()`. In `--data` mode, `run()` is called once per data row. The MiniLM-L6-v2 sentence-transformer model (used for semantic resolution in Phase 2) may be loaded fresh each time.

**What the fix gives:** The resolver is built once before the `--data` loop and passed into each `run()` call. The model is loaded once. Memory and startup time per row drops significantly.

---

### E3 — Full browser launch per `--data` row

**What is wrong:** Each `asyncio.run(run(...))` call in the `--data` loop:
1. Starts a new `async_playwright()` process
2. Launches a full Chromium browser
3. Builds an `ElementResolver` (possibly loading the MiniLM-L6-v2 sentence-transformer model)
4. Constructs all reporters and opens file handles
5. Tears everything down

For 10 data rows this happens 10 times. A 50-row test matrix wastes minutes on startup overhead alone.

**What the fix gives:** One browser launch, one model load, one resolver — shared across all rows. Each row gets a fresh browser context (isolated state) but not a fresh process.

---

### E5 — Triple mkdir for screenshots_dir

**What is wrong:** The same directory path has `Path.mkdir(parents=True, exist_ok=True)` called from three different places:
- `main.py` fallback branch
- `ScreenshotAction.__init__`
- `StepRunner.__init__`

Each `mkdir` is a filesystem syscall. In `--data` mode these fire three times per row.

**What the fix gives:** The directory is created once in `main.py`. The constructor `mkdir` calls are removed, and both objects trust the caller to have prepared the path. Simpler, cheaper, and the responsibility is correctly placed at the composition root.

---

## CS-6 — Runtime Efficiency

### E8 — Unnecessary deepcopy on every step

**What is wrong:** `_resolve_context_vars` does `copy.deepcopy(step.extra)` on every step once `ctx.counts` is non-empty. Most steps have no `{{` tokens in their `extra` dict and need no substitution. The deepcopy is paid anyway.

**What the fix gives:** A cheap string scan (`"{{" in json.dumps(step.extra)`) before the deepcopy skips the allocation for steps that carry no templates. For workflows with many steps and few template-using ones, this avoids most deepcopy calls.

---

### E9 — No per-step screenshot opt-out

**What is wrong:** `StepRunner` captures a screenshot after every step that doesn't already have one. For a workflow with 30 sub-steps inside a `for_each` loop, this means 30 PNG captures — each blocking the Playwright event loop while the browser renders and compresses the image.

**What the fix gives:** Steps that run frequently (e.g. inside loops) can set `"skip_screenshot": true`. Screenshot overhead is concentrated on the steps that actually need visual record.

---

## CS-7 — Constants, Docstrings, and Typing Polish

### R3 — Magic literal 0.80 instead of CONFIDENCE_AUTO

**What is wrong:** `ResolveResult.is_high_confidence` returns `self.confidence >= 0.80`. `CONFIDENCE_AUTO = 0.80` is the named constant for exactly this threshold and is imported in the same file. If `CONFIDENCE_AUTO` is ever tuned, the property silently diverges.

**What the fix gives:** Single source of truth. Change the constant, all comparisons update automatically.

---

### Q13 — GlueAction._build_pom is untyped

**What is wrong:** `_build_pom(pom_cls, *args, page, resolver, **kwargs)` — `pom_cls` is untyped, return type is untyped. IDEs see `Any`. Attribute access on the returned POM is unchecked by mypy.

**What the fix gives:** With `TypeVar T`, `_build_pom(LoginPage, ...)` returns `LoginPage`. IDE autocomplete works. Mypy catches attribute typos. The safety guarantee the method is designed to provide gets tooling support.
