# Conversation Prompts

Each prompt below is a self-contained briefing for a fresh Claude conversation.
Paste one prompt per conversation. Each covers one change set from [implementation_plan.md](implementation_plan.md).

---

## CS-1 — P1 Correctness Fixes

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read the following files before making any changes:
- stepper/engine/actions/strategies.py
- stepper/engine/actions/factory.py

Make these three targeted fixes:

FIX 1 — ScreenshotAction filename precedence bug (strategies.py ~line 237):
  The expression:
    name = step.extra.get("filename") or f"{ts}_step.png" if step.extra else f"{ts}_step.png"
  has a Python operator-precedence bug — the ternary binds to the `or` right side,
  not the whole expression. Fix it to:
    name = step.extra.get("filename") or f"{ts}_step.png"
  (StepConfig.extra is always a dict with default_factory=dict, so the None-guard is unnecessary.)

FIX 2 — Remove hardcoded #username selector from EnsureLoginAction (strategies.py ~line 470):
  Replace:
    await page.wait_for_selector("#username", state="visible", timeout=10_000)
  With:
    ready_selector = step.extra.get("form_ready_selector")
    if ready_selector:
        await page.wait_for_selector(ready_selector, state="visible", timeout=10_000)
  This removes an OpenLibrary-specific CSS selector from the generic engine layer.
  Update the OpenLibrary glue login action to pass "form_ready_selector": "#username" in step.extra.

FIX 3 — PaginateAction bypasses ActionFactory (strategies.py ~line 762):
  Replace:
    await ExtractDataAction()._execute(page, extract_step, resolver, context)
  With:
    action = self._factory.create("extract_data")
    await action.execute(page, extract_step, resolver, context)
  PaginateAction already holds self._factory. This restores pre/post hook execution
  and observer notification for extract sub-steps inside pagination.

No other changes. Do not refactor surrounding code.

When done, update strategy/progress.md — mark CS-1 items [x] in the P1 table and the Change Set Summary.
```

---

## CS-2 — main.py Cleanup

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read stepper/main.py before making any changes.

Make these targeted cleanups to main.py:

FIX 1 — Remove redundant cfg_headless variable (~line 103, 109):
  cfg_headless = not headless appears in both try and except blocks with the same value.
  Hoist it above the try/except block and remove from both branches.

FIX 2 — Honour cfg_browser when launching the browser (~line 141):
  Currently: browser = await pw.chromium.launch(...)
  Replace with a dict dispatch:
    _launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
    browser = await _launchers.get(cfg_browser, pw.chromium).launch(headless=headless, slow_mo=slow_mo)

FIX 3 — Keep TestReportReporter as a direct variable (~line 126-145):
  Construct test_reporter as a named variable before building the reporters list.
  Append it into the list. Remove the next(isinstance(...)) scan below.

FIX 4 — Merge the two test_reporter guard blocks (~lines 150-164):
  There are two consecutive `if test_reporter and test_reporter.manager.current_test_dir:` blocks.
  Merge them into one block that sets up both the log handler and screenshots_dir.

FIX 5 — Document RunWorkflowAction temporal coupling (~line 203):
  Add a clear comment above the registration line explaining that it MUST come after
  StepRunner is created because it closes over runner.run.

FIX 6 — Deduplicate allure serve subprocess call (~lines 223, 276):
  Extract a one-liner helper _serve_allure() and call it from both places.

No other changes.

When done, update strategy/progress.md — mark CS-2 items [x] in the P2/P3/P4 tables and the Change Set Summary.
```

---

## CS-3 — Sub-step Loop Merge + JSON Round-trip Removal

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read stepper/engine/actions/strategies.py before making any changes.

Make these changes to strategies.py:

CHANGE 1 — Hoist `import json` to module level:
  There are two `import json` statements buried inside method bodies
  (inside ForEachItemAction._execute and EnsureLoginAction._execute).
  Move both to the top-level imports at the top of the file.

CHANGE 2 — Add a recursive dict-walk substitution helper:
  Add this module-level function near the top of strategies.py (after imports):

    def _apply_substitutions(obj, subs: dict):
        """Recursively replace {{key}} tokens in a dict/list/str structure."""
        if isinstance(obj, str):
            for k, v in subs.items():
                obj = obj.replace(f"{{{{{k}}}}}", str(v))
            return obj
        if isinstance(obj, dict):
            return {k: _apply_substitutions(v, subs) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_apply_substitutions(i, subs) for i in obj]
        return obj

CHANGE 3 — Add a shared _run_sub_steps() helper:
  Add this async helper function near the top of strategies.py:

    async def _run_sub_steps(factory, steps_raw: list[dict], page, resolver, context,
                              substitutions: dict | None = None,
                              stop_on_failure: bool = False):
        import copy
        results = []
        for raw in steps_raw:
            cfg_dict = copy.deepcopy(raw)
            if substitutions:
                cfg_dict = _apply_substitutions(cfg_dict, substitutions)
            sub_cfg = _dict_to_step_config(cfg_dict)
            action = factory.create(sub_cfg.action)
            result = await action.execute(page, sub_cfg, resolver, context)
            results.append(result)
            if stop_on_failure and result.status != "passed":
                break
        return results

CHANGE 4 — Refactor ForEachItemAction._execute to use _run_sub_steps:
  Replace the inner loop (the json.dumps → .replace → json.loads part and the action.execute call)
  with a call to _run_sub_steps, passing substitutions built from item_url, book_url, index,
  and any item.<key> values. Preserve the existing `when` condition evaluation per sub-step.

CHANGE 5 — Refactor EnsureLoginAction._execute to use _run_sub_steps:
  Replace the `for raw in login_steps` loop (the json.dumps → json.loads no-op and action.execute call)
  with a call to _run_sub_steps(stop_on_failure=True).
  Keep the existing error-propagation behaviour (return failed result on first failure).

No other changes.

When done, update strategy/progress.md — mark CS-3 items [x] in the P3/P4 tables and the Change Set Summary.
```

---

## CS-4 — strategies.py and step_runner.py Quality Fixes

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read these files before making any changes:
- stepper/engine/actions/strategies.py
- stepper/engine/runner/step_runner.py

Make these targeted quality fixes:

FIX 1 — Extract env-resolution preamble into a helper (strategies.py ~lines 72-78, 122-128):
  Add a module-level helper:
    def _checked_input_value(step):
        value, was_env = _resolve_input_value(step.input_value)
        if was_env and not value:
            return "", StepResult(step=step, status="failed",
                                  error=f"Missing env var for '{step.input_value}'")
        return value, None
  Use it in ClickAction and FillAction. Early-return when the second element is not None.

FIX 2 — Add press_enter opt-out to FillAction (strategies.py ~line 138):
  Replace:
    await result.locator.press("Enter")
  With:
    if step.extra.get("press_enter", True):
        await result.locator.press("Enter")

FIX 3 — Remove dead `if step.extra else None` guards in SelectAction (strategies.py ~lines 200-201):
  StepConfig.extra is always a dict (default_factory=dict). Replace:
    label = step.extra.get("label") if step.extra else None
    index = step.extra.get("index") if step.extra else None
  With:
    label = step.extra.get("label")
    index = step.extra.get("index")

FIX 4 — Extract _fetch_attr helper in ExtractDataAction (strategies.py ~lines 629-652):
  The attr-fetching switch (innerText / innerHTML / textContent / generic attribute) is
  written out twice — for single-attr and multi-attr cases. Extract:
    async def _fetch_attr(locator, attr: str) -> str:
        if attr == "innerText": return (await locator.inner_text()).strip()
        if attr == "innerHTML": return await locator.inner_html()
        if attr == "textContent": return (await locator.text_content() or "").strip()
        return await locator.get_attribute(attr) or ""
  Use it in both branches of ExtractDataAction._execute.

FIX 5 — Extract _notify helper in StepRunner (step_runner.py ~lines 145-164):
  The three _notify_start, _notify_done, _notify_log methods share identical
  for/try/except structure. Add:
    def _notify(self, method: str, *args):
        for obs in self._observers:
            try:
                getattr(obs, method)(*args)
            except Exception:
                pass
  Then have each _notify_* call self._notify("on_...", ...).

FIX 6 — Rename _resolve_context_vars (step_runner.py ~line 169):
  Rename to _resolve_count_vars. Add a comment explaining it only substitutes
  ctx.counts values and that other context fields are handled by ForEachItemAction directly.

No other changes.

When done, update strategy/progress.md — mark CS-4 items [x] in the P2/P3/P4 tables and the Change Set Summary.
```

---

## CS-5 — Data-mode Performance

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read stepper/main.py before making any changes.

Make these performance improvements for --data mode:

FIX 1 — Move _load_env() inside main() (~line 41):
  Remove the top-level call _load_env() at module scope.
  Add _load_env() as the first line inside the main() function body.
  This prevents filesystem reads on every test import.

FIX 2 — Build ElementResolver once outside the --data loop (~lines 117-122, 263-273):
  The resolver is currently built inside run(). For --data mode it should be built
  once before the loop in main() and passed into run() as an optional parameter.
  Add `resolver=None` to run()'s signature. When provided, skip construction inside run().

FIX 3 — Reuse browser across --data rows (~lines 263-273):
  Refactor the --data loop to open one playwright instance and one browser,
  then run each row in a fresh context (new_context()) within the same browser.
  Extract an async helper `_run_data_rows(rows, cli_vars, args)` that owns the browser
  lifecycle and calls a per-row function for each row.
  Each row still gets an isolated browser context (so auth state, cookies, etc. are fresh).

FIX 4 — Single mkdir for screenshots_dir (~main.py:164, strategies.py:232, step_runner.py:54):
  After determining screenshots_dir in main.py, call mkdir once there.
  Remove the mkdir call from ScreenshotAction.__init__ (it trusts the caller created the dir).
  Remove the mkdir call from StepRunner.__init__ (same reason).

No other changes.

When done, update strategy/progress.md — mark CS-5 items [x] in the P2/P3 tables and the Change Set Summary.
```

---

## CS-6 — Runtime Efficiency

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read these files before making any changes:
- stepper/engine/runner/step_runner.py
- stepper/engine/actions/strategies.py
- stepper/main.py

Make these runtime efficiency improvements:

FIX 1 — Guard deepcopy with {{ token scan (step_runner.py ~line 198):
  In _resolve_count_vars (or _resolve_context_vars), before deepcopying step.extra,
  add a cheap scan:
    import json
    if "{{" not in json.dumps(step.extra):
        return step
  This skips deepcopy for the majority of steps that carry no template tokens.

FIX 2 — Add per-step skip_screenshot flag (step_runner.py ~line 117, interfaces.py):
  Add `skip_screenshot: bool = False` to StepConfig.
  In StepRunner.run(), change the auto-screenshot condition to:
    if self._screenshots_dir and not result.screenshot and not step.skip_screenshot:
  This lets high-frequency sub-steps (inside for_each loops) opt out of screenshot capture.

FIX 3 — Move MeasurePerformanceAction output dir creation to __init__ (strategies.py ~line 534):
  Add __init__(self) to MeasurePerformanceAction that stores the default output path
  and calls mkdir once. In _execute, still allow step.extra override but only call mkdir
  if the path changed from the stored default. (Or simpler: always mkdir in __init__ for
  the default path; custom paths can mkdir in _execute as a one-time guard.)

FIX 4 — Guard storage_state write (main.py ~lines 214-216):
  Only write storage state when authentication steps actually ran.
  Simplest approach: check if any step in `results` has action name matching known login actions
  (e.g. "ol_ensure_login", "sd_login", "ensure_login"). If none did, skip the write.
  Alternative: add a _session_dirty flag to ExecutionContext, set it in login glue actions.

No other changes.

When done, update strategy/progress.md — mark CS-6 items [x] in the P3/P4 tables and the Change Set Summary.
```

---

## CS-7 — Constants, Docstrings, and Typing Polish

**Paste this as the opening message of a new conversation:**

```
I'm working in a Playwright + Python automation framework.
Please read these files before making any changes:
- stepper/engine/interfaces.py
- stepper/engine/pages/glue_action.py
- stepper/main.py (only the _load_env function)

Make these low-risk polish changes:

FIX 1 — Use CONFIDENCE_AUTO constant in ResolveResult.is_high_confidence (interfaces.py ~line 67):
  Replace:
    return self.confidence >= 0.80
  With:
    return self.confidence >= CONFIDENCE_AUTO
  CONFIDENCE_AUTO is already imported at line 26 of the same file.

FIX 2 — Fix ExecutionContext docstring (interfaces.py ~line 101):
  The docstring lists `collected_books` as a backward-compat alias field.
  It is not a field. Replace the collected_books entry with an accurate note:
    "Legacy page._collected_books is accessed by ForEachItemAction as a page-attribute
     fallback — not a typed field on this class."

FIX 3 — Add TypeVar to GlueAction._build_pom (glue_action.py ~line 51):
  Add:
    from typing import TypeVar, Type
    T = TypeVar("T")
  Change the signature from:
    def _build_pom(pom_cls, *args, page, resolver, **kwargs)
  To:
    def _build_pom(pom_cls: Type[T], *args, page, resolver, **kwargs) -> T:
  This gives IDEs and mypy the return type from the class passed in.

FIX 4 — Document or replace _load_env() with python-dotenv (main.py ~lines 21-38):
  Option A: Add a docstring warning that quoted values and multi-line .env values
  are not supported by the custom parser.
  Option B (preferred if python-dotenv is acceptable): Replace the function with:
    from dotenv import load_dotenv
    def _load_env():
        load_dotenv(override=False)
  And add python-dotenv to requirements.txt.

No other changes.

When done, update strategy/progress.md — mark CS-7 items [x] in the P4 table and the Change Set Summary.
```
