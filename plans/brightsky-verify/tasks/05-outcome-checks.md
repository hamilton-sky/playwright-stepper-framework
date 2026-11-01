# Add the per-step outcome checks and the conversion to BrightSky step outcomes

Type: task
Status: open
Blocked by: 03, 12
Test first: yes
Level: 3
Touches: stepper/brightsky/executor.py, stepper/engine/runner/step_runner.py, stepper/tests/unit/test_brightsky_executor.py, stepper/tests/unit/test_step_hooks.py

`stepper/brightsky/executor.py` (new) gets the pieces that decide each step's outcome.
The executors that run them (`EngineExecutor`, `PipelineExecutor`) are ticket 13. Level 3,
because this is where "passed" is decided, and a passed report auto-verifies a version.
It is blocked by 12 because both change `step_runner.py`, and `executed_steps` reads the
`healed_element["tier"]` that 12 adds.

- **`StepRunner.add_hook(domain: str | None, hook: StepHook) -> StepRunner`.** Add this
  next to `add_observer` in `step_runner.py`. It appends to `self._hooks[domain]` and
  returns self. Replacement runners in the heal loop are built with `hooks=self._hooks`,
  so they see an added hook. That is intended: a heal whose replacement misses the
  outcome is not a heal.
- **`RecordingResolver(inner)`.**
  - `set_context_description` passes through and remembers the description.
  - `resolve(page, cfg, step_description="", *, strict=False, action=None)` delegates.
    On the *first* resolve for a description, it records `result.method` if found, else
    `None`. Later resolves (retries, heal replacements) do not overwrite it. So `tiers`
    describe the stored target, not the heal.
  - Every other attribute is delegated with `__getattr__`.
- **`ExpectationHook(expectations, timeout_s=10.0, poll_s=0.25)`**, a `StepHook`.
  - `before`: when the step's expectation has a `start_url`, the page's pathname (from
    `urllib.parse.urlparse(session.url).path`) must satisfy ticket 03's `url_matches`.
    If it does not, return a failed `StepResult` with error `not on the expected page:
    <path> does not match <expected> (<mode>)`.
  - `after`: when the result is `passed` or `healed` and an outcome is set, poll until
    it holds or the timeout ends. If it does not hold, set `status="failed"` and
    `error="expected outcome not met: <what>"`. The checks:
    - `url_change`: `urlContains` is in `session.url`;
    - `element_appears`: a locator built from the outcome's element cfg has a count
      above 0;
    - `element_gone`: the count is 0;
    - `value_set`: Playwright's `Locator.input_value()` (map.md has the docs line)
      equals the step's `input_value`.
    - Locators: `get_by_role(role, name=name, exact=True)`, `get_by_text(text,
      exact=True)`, `locator(css)`, `locator("xpath=" + xpath)`, or `locator("#" + id)`.
  - An exception inside a check counts as not met. It is logged and never swallowed as a
    pass, because this hook is a gate.
- **`ExecutedStep`** (frozen dataclass, fields in spec.md § Interfaces) and
  **`executed_steps(mapped, results, tiers) -> list[ExecutedStep]`.** For each BrightSky
  step number from 1 to n in order, take the *last* StepResult whose description maps to
  that number:
  - none → `unchecked`, `matched=False`, `tier=None`;
  - `passed` → `passed`, `matched=True`, tier from `tiers`;
  - `healed` → `failed`, `healed=True`, `matched=False`,
    `tier=(healed_element or {}).get("tier", "healer")`, with `healed_element` kept, which
    is None after a scroll/wait injection (brief, Decided: a healed step must not count
    as passed);
  - anything else → `failed`, with `matched` true only when `tiers` has a method for
    that step, `tier` that method or None, and `error` the result's error.
- **`StepExecutor`**, the Protocol: `async execute(mapped, *, headless) ->
  list[ExecutedStep]`.

## Not in this ticket

- The two executors that build a runner, attach these pieces and run it; ticket 13.
- Talking to the backend and deciding pass/fail for the whole run; ticket 06.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_executor.py -q` passes. With fake
  pages and a short timeout, its hook tests show `url_change` met and not met, a
  `value_set` whose `input_value()` raises counting as not met, and a `start_url`
  mismatch failing the step before the action runs.
- In the same file, `RecordingResolver` keeps the first method for a description and
  passes `strict` through to the inner resolver unchanged.
- In the same file, `executed_steps` maps passed, healed (with and without
  `healed_element`), failed, outcome-failed (`matched=True`), unchecked, and a failed
  navigate (step 1 failed) correctly.
- `python3 -m pytest stepper/tests/unit/test_step_hooks.py -q` passes, with new tests
  showing a hook added through `add_hook` runs for its domain only and is seen by a heal
  replacement runner.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_executor.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/test_step_hooks.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("Where outcome checks run", "Healed means failed"), § Interfaces
- map.md § Decisions so far (`Locator.input_value` source)
- `stepper/engine/runner/hooks.py` (`StepHook` contract),
  `stepper/engine/resolvers/shadow_runner.py` (an existing resolver wrapper)

## Answer
