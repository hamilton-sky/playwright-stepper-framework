# Solutions

Each solution is cross-referenced from [findings.md](findings.md). Solutions are grouped by the file they touch.

---

## Reuse Solutions

### S-R1
**Fix duplicated sub-step dispatch loop** → [R1](findings.md#r1)

Extract a shared helper at the top of `strategies.py`:

```python
async def _run_sub_steps(factory, steps_raw: list[dict], page, resolver, context,
                          substitutions: dict | None = None,
                          stop_on_failure: bool = False) -> list[StepResult]:
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
```

`ForEachItemAction` passes `substitutions={"item_url": ..., "index": ...}` and `stop_on_failure=False`.
`EnsureLoginAction` passes no substitutions and `stop_on_failure=True`.

---

### S-R2
**Deduplicate `allure serve` call** → [R2](findings.md#r2)

Extract into a one-liner helper inside `main.py`:

```python
def _serve_allure():
    import subprocess
    subprocess.run(["allure", "serve", str(_stepper_root / "reports" / "allure-results")])
```

Call `_serve_allure()` in both places. Or: consolidate — the `--data` branch already passes `allure_serve=False` per row, so just call `_serve_allure()` once at the end if `args.allure_serve`.

---

### S-R3
**Use `CONFIDENCE_AUTO` constant in `is_high_confidence`** → [R3](findings.md#r3)

In `interfaces.py:67`:
```python
# Before
return self.confidence >= 0.80
# After
return self.confidence >= CONFIDENCE_AUTO
```

---

### S-R4
**Replace JSON round-trip with direct dict substitution** → [R4](findings.md#r4)

Add a recursive helper (reuses `copy` already imported in `step_runner.py`):

```python
def _apply_substitutions(obj, subs: dict):
    if isinstance(obj, str):
        for k, v in subs.items():
            obj = obj.replace(f"{{{{{k}}}}}", str(v))
        return obj
    if isinstance(obj, dict):
        return {k: _apply_substitutions(v, subs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_apply_substitutions(i, subs) for i in obj]
    return obj
```

Used by S-R1. Eliminates both the `json.dumps → .replace → json.loads` and the no-op round-trip in `EnsureLoginAction`.

---

### S-R5
**Hoist `import json` to module level** → [R5](findings.md#r5)

Move both `import json` statements inside `ForEachItemAction._execute` and `EnsureLoginAction._execute` to the top-level imports block in `strategies.py`. Python caches imports so there is no cost, but top-level imports make dependencies visible.

---

### S-R6
**Dispatch `ExtractDataAction` through the factory in `PaginateAction`** → [R6](findings.md#r6)

`PaginateAction` already holds `self._factory`. Replace:
```python
# Before
await ExtractDataAction()._execute(page, extract_step, resolver, context)
# After
action = self._factory.create("extract_data")
await action.execute(page, extract_step, resolver, context)
```

This restores pre/post hook execution and observer notification.

---

### S-R7
**Keep `TestReportReporter` as a direct variable** → [R7](findings.md#r7)

In `main.py`, construct the reporter before the list and append it:
```python
test_reporter = TestReportReporter(
    reports_base=str(_stepper_root / "reports"),
    test_name=run_label, browser=cfg_browser, headless=cfg_headless,
)
reporters = [
    ConsoleReporter(),
    JsonReporter(str(_stepper_root / "report.json")),
    test_reporter,
    AllureReporter(str(_stepper_root / "reports" / "allure-results")),
]
# No `next(isinstance(...))` needed below
```

---

### S-R8
**Adopt `python-dotenv` or document the parser's limitations** → [R8](findings.md#r8)

Option A (recommended): Replace `_load_env()` with `python-dotenv`:
```python
from dotenv import load_dotenv
load_dotenv(override=False)   # don't override real env vars
```

Add `python-dotenv` to `requirements.txt`.

Option B (minimal): Document in the function's docstring that quoted values and multi-line values are not supported.

---

### S-R9
**Make the ready-selector configurable in `EnsureLoginAction`** → [R9](findings.md#r9)

Replace the hardcoded line:
```python
# Before
await page.wait_for_selector("#username", state="visible", timeout=10_000)
# After
ready_selector = step.extra.get("form_ready_selector")
if ready_selector:
    await page.wait_for_selector(ready_selector, state="visible", timeout=10_000)
```

OpenLibrary glue can then pass `"form_ready_selector": "#username"` in `step.extra`. The engine layer stays generic.

---

## Quality Solutions

### S-Q1
**Remove redundant `cfg_headless` variable** → [Q1](findings.md#q1)

`cfg_headless` has the same value (`not headless`) in both branches. Hoist it above the `try/except` and remove from both branches, or pass `not headless` directly to `TestReportReporter`.

---

### S-Q2
**Honour `cfg_browser` when launching the browser** → [Q2](findings.md#q2)

```python
# Before
browser = await pw.chromium.launch(headless=headless, slow_mo=slow_mo)
# After
launcher = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
browser = await launcher.get(cfg_browser, pw.chromium).launch(headless=headless, slow_mo=slow_mo)
```

---

### S-Q3
**Merge the two `test_reporter` guard blocks** → [Q3](findings.md#q3)

```python
if test_reporter and test_reporter.manager.current_test_dir:
    run_dir = test_reporter.manager.current_test_dir
    # log handler setup
    log_path = run_dir / "logs" / "run.log"
    log_handler = logging.FileHandler(log_path, encoding="utf-8")
    ...
    logging.getLogger().addHandler(log_handler)
    # screenshots dir
    screenshots_dir = test_reporter.manager.get_screenshots_dir()
else:
    log_handler = None
    screenshots_dir = _stepper_root / "artifacts" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
```

---

### S-Q4
**Make `RunWorkflowAction` temporal coupling explicit** → [Q4](findings.md#q4)

Document the ordering constraint with a comment, or encapsulate registration in a factory method:
```python
# MUST be registered after StepRunner is created — needs runner.run reference
action_registry.register(RunWorkflowAction(run_steps_callable=runner.run, base_dir=base_dir))
```

Longer term: pass `runner` into `RunWorkflowAction` lazily (via a `Callable` that is resolved at call time) so the dependency is injected, not closed over.

---

### S-Q5
**Extract env-resolution preamble into a helper** → [Q5](findings.md#q5)

```python
def _checked_input_value(step: StepConfig) -> tuple[str, StepResult | None]:
    value, was_env = _resolve_input_value(step.input_value)
    if was_env and not value:
        return "", StepResult(step=step, status="failed",
                              error=f"Missing env var for '{step.input_value}'")
    return value, None
```

`ClickAction` and `FillAction` call it and early-return if the second element is not `None`.

---

### S-Q6
**Add `press_enter` opt-out to `FillAction`** → [Q6](findings.md#q6)

```python
# Before
await result.locator.press("Enter")
# After
if step.extra.get("press_enter", True):
    await result.locator.press("Enter")
```

Workflow steps that just want to fill without submitting set `"extra": {"press_enter": false}`.

---

### S-Q7
**Remove dead `if step.extra else None` guards** → [Q7](findings.md#q7)

`StepConfig.extra` is always a `dict`. Replace:
```python
# Before
label = step.extra.get("label") if step.extra else None
index = step.extra.get("index") if step.extra else None
# After
label = step.extra.get("label")
index = step.extra.get("index")
```

---

### S-Q8
**Fix `ScreenshotAction` filename precedence bug** → [Q8](findings.md#q8)

```python
# Before (buggy — ternary binds to `or` right side)
name = step.extra.get("filename") or f"{ts}_step.png" if step.extra else f"{ts}_step.png"
# After (correct)
name = (step.extra.get("filename") or f"{ts}_step.png") if step.extra else f"{ts}_step.png"
# Or simplest (extra is always a dict, guard is unnecessary):
name = step.extra.get("filename") or f"{ts}_step.png"
```

---

### S-Q9
**Rename `_resolve_context_vars` and document its scope** → [Q9](findings.md#q9)

Rename to `_resolve_count_vars` to match what it actually does. Add a comment explaining that `collected_items` / `extracted_data` substitution is intentionally out of scope (handled by `ForEachItemAction` directly).

---

### S-Q10
**Extract a single `_notify` helper in `StepRunner`** → [Q10](findings.md#q10)

```python
def _notify(self, method: str, *args):
    for obs in self._observers:
        try:
            getattr(obs, method)(*args)
        except Exception:
            pass

def _notify_start(self, idx, step):    self._notify("on_step_start", idx, step)
def _notify_done(self, idx, result):   self._notify("on_step_done", idx, result)
def _notify_log(self, msg, level="info"): self._notify("on_log", msg, level)
```

---

### S-Q11
**Fix `ExecutionContext` docstring** → [Q11](findings.md#q11)

Remove the `collected_books` entry from the docstring or replace it with an accurate note:

```
collected_items  - URLs or item dicts produced by collect_items.
                   Legacy page._collected_books accessed by ForEachItemAction
                   as a fallback — not a typed field on this class.
```

---

### S-Q12
**Extract `_fetch_attr` coroutine in `ExtractDataAction`** → [Q12](findings.md#q12)

```python
async def _fetch_attr(locator, attr: str) -> str:
    if attr == "innerText":
        return (await locator.inner_text()).strip()
    if attr == "innerHTML":
        return await locator.inner_html()
    if attr == "textContent":
        return (await locator.text_content() or "").strip()
    return await locator.get_attribute(attr) or ""
```

Both the single-attr and multi-attr branches call `_fetch_attr` — no duplication.

---

### S-Q13
**Add `TypeVar` to `GlueAction._build_pom`** → [Q13](findings.md#q13)

```python
from typing import TypeVar, Type
T = TypeVar("T")

@staticmethod
def _build_pom(pom_cls: Type[T], *args, page, resolver, **kwargs) -> T:
    return pom_cls(*args, page=page, resolver=resolver, **kwargs)
```

IDEs and mypy now infer the correct return type from the class passed in.

---

## Efficiency Solutions

### S-E1
**Move `_load_env()` call inside `main()`** → [E1](findings.md#e1)

```python
# Remove line 41: _load_env()

def main():
    _load_env()   # first line of main() — only fires when CLI is used
    parser = argparse.ArgumentParser(...)
    ...
```

Tests that `import run` no longer pay the filesystem stat.

---

### S-E2
**Build `ElementResolver` once outside `run()`** → [E2](findings.md#e2)

In `--data` mode in `main()`:
```python
# Build resolver once before the loop
resolver_factory = DefaultResolverFactory()
resolver = ElementResolver(strategies=resolver_factory.build_cascade(), ...)

for i, row in enumerate(rows, 1):
    asyncio.run(run(..., resolver=resolver))   # pass in pre-built resolver
```

`run()` gains an optional `resolver` parameter; if provided, it skips construction.

---

### S-E3
**Reuse the browser across `--data` rows** → [E3](findings.md#e3)

Refactor `run()` to accept an optional `browser` / `context` argument, or extract a `_run_with_browser(browser, ...)` inner function:

```python
async def _run_all_data_rows(rows, cli_vars, args):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(...)
        for i, row in enumerate(rows, 1):
            merged = {**row, **cli_vars}
            await _run_with_context(browser, merged, args)
        await browser.close()
```

This gives one browser launch for all rows instead of N.

---

### S-E4
**Guard storage state write with a dirty flag** → [E4](findings.md#e4)

```python
_session_dirty = False

# In OLLoginPage or EnsureLoginAction, after successful login:
_session_dirty = True

# In main.py:
if storage_state_path and _session_dirty:
    await context.storage_state(path=str(storage_state_path))
```

Alternatively, always write but only on runs that contain login steps (check `steps` list for login action names).

---

### S-E5
**Single `mkdir` for `screenshots_dir`** → [E5](findings.md#e5)

Create the directory once in `main.py` after the path is determined, then pass the already-created `Path` into `build_default_registry` and `StepRunner`. Remove the `mkdir` calls from `ScreenshotAction.__init__` and `StepRunner.__init__`. Both constructors can rely on the caller having already created the directory.

---

### S-E6
**Replace JSON round-trip with direct dict substitution** → [E6](findings.md#e6)

Same as [S-R4](solutions.md#s-r4). The `_apply_substitutions` recursive dict-walk replaces the `json.dumps → .replace → json.loads` pattern, running in O(items × sub_steps × len(subs)) string ops instead of also paying the JSON codec.

---

### S-E7
**Move `mkdir` to `MeasurePerformanceAction.__init__`** → [E7](findings.md#e7)

```python
def __init__(self, output_path: Path = Path("artifacts/performance.json")):
    self._output_path = output_path
    self._output_path.parent.mkdir(parents=True, exist_ok=True)
```

`_execute` uses `self._output_path` (or overrides from `step.extra`) without calling `mkdir`.

---

### S-E8
**Skip `deepcopy` when `extra` has no template tokens** → [E8](findings.md#e8)

```python
def _resolve_count_vars(step: StepConfig, ctx: ExecutionContext) -> StepConfig:
    if not ctx.counts:
        return step
    # Cheap scan before paying deepcopy cost
    import json
    raw = json.dumps(step.extra)
    if "{{" not in raw:
        return step
    resolved_extra = _sub(json.loads(raw), ctx.counts)
    return dataclasses.replace(step, extra=resolved_extra) if resolved_extra != step.extra else step
```

The `json.dumps` scan is cheaper than `copy.deepcopy` for typical `extra` dict sizes.

---

### S-E9
**Add per-step `skip_screenshot` opt-out** → [E9](findings.md#e9)

Add a field to `StepConfig`:
```python
skip_screenshot: bool = False
```

In `StepRunner.run()`:
```python
if self._screenshots_dir and not result.screenshot and not step.skip_screenshot:
    ...
```

Workflow steps that run frequently (e.g. sub-steps inside `for_each`) can set `"skip_screenshot": true`.

---

### S-E10
**Batch attribute extraction with `evaluate_all`** → [E10](findings.md#e10)

```python
# Instead of: for loc in locators: await loc.get_attribute(attr)
values = await page.locator(css).evaluate_all(
    "(els, attr) => els.map(el => el.getAttribute(attr) ?? el.innerText)",
    attr
)
```

Reduces N_locators async round-trips to one JS call per attribute.

---
