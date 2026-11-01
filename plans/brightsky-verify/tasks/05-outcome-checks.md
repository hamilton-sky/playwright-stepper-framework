# Add the per-step outcome checks and the conversion to BrightSky step outcomes

Type: task
Status: resolved
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

- **Built**: `stepper/brightsky/executor.py` (new: `ExecutedStep`, `StepExecutor`,
  `RecordingResolver`, `ExpectationHook`, `executed_steps`), `StepRunner.add_hook` in
  `stepper/engine/runner/step_runner.py` (next to `add_observer`), tests in
  `stepper/tests/unit/test_brightsky_executor.py` (new) and
  `stepper/tests/unit/test_step_hooks.py` (4 new tests). Work started at 7d099e7. The
  test-only commit 8a3f654 failed for the right reasons: the executor file failed at
  collection with `ModuleNotFoundError: No module named 'stepper.brightsky.executor'`, and
  4 hook tests failed with `AttributeError` (no `add_hook`).
- **Proof**:
  - `python3 -m pytest stepper/tests/unit/test_brightsky_executor.py -q` printed `46 passed`.
    The hook tests use fake pages with `timeout_s=0.05, poll_s=0.01`. They cover:
    `url_change` met, not met, and met after polling;
    `value_set` with `input_value()` raising, on a non-input, equal, and different;
    `element_appears` and `element_gone` met and not met; a `count()` that raises counts
    as not met; each locator kind (role+name `exact=True`, text `exact=True`, css,
    `xpath=`, `#id`); a failed step is left unchecked; a healed step that misses its outcome
    is failed. For `before`: a match, a `startsWith` mismatch (with the exact error text),
    the `includes` mode, and no start_url. In a real `StepRunner` run, a `start_url`
    mismatch fails the step with `action.calls == 0`, and an unmet outcome fails it after
    the action ran.
  - RecordingResolver: the first method is kept (`role`, not the later `css`), a first miss
    stays `None`, each description is recorded separately, the context description is used
    when none is passed, `strict` True/False and `action` reach the inner resolver
    unchanged (exact args and kwargs), the inner result is returned unchanged, and other
    attributes are delegated.
  - executed_steps: all passed; healed with `healed_element` (tier `cheap`, kept), healed
    without it (`healer`, None), and a healed_element with no tier (`healer`); failed and
    unmatched (step 3 unchecked); outcome-failed `matched=True, tier="css"`; a failed
    navigate gives step 1 failed and 2 and 3 unchecked; no results gives all unchecked;
    the last result per number wins; an unmapped description is ignored. Also checked:
    ExecutedStep is frozen, a stub class passes `isinstance(..., StepExecutor)`, and
    ExpectationHook is a StepHook.
  - `python3 -m pytest stepper/tests/unit/test_step_hooks.py -q` printed `21 passed`. New:
    add_hook returns the runner; hooks added for `web` and `other` each run only for their
    own domain's step; an added hook runs after the constructor's hooks; and in a heal
    (non-strict, capture and VisualBridge monkeypatched), the log reads `before, before,
    after(passed), after(healed)`, so the replacement runner ran the added hook.
  - `python3 -m pytest stepper/tests/unit/ -q` printed `2067 passed`, exit 0. Build
    (`compileall`) exited 0. Lint (`main.py validate`) exited 0. Acceptance has 82 passed and
    79 failed; the failures are in the verify/CLI/executor tests of tickets 06, 07 and 13.
    `test_add_hook_attaches_a_hook_for_its_domain_and_returns_the_runner` passes.
- **Decisions**:
  - The RecordingResolver key is `step_description or` the last context description.
    Actions pass `step.description`, and the runner sets the same value as context.
  - When `before` cannot read `session.url`, it returns a failed result
    (`not on the expected page: cannot read the page URL (...)`) instead of raising. The
    runner logs a hook that raises and then runs the step anyway, which would bypass the
    gate.
  - A `url_change` with no `urlContains` counts as met. The ticket only defines the
    urlContains check, and mapping stores None when there is none.
  - The outcome locator takes the first present key, in the order the ticket lists:
    role+name, text, css, xpath, id. An element cfg with none of these raises inside the
    check, so the outcome is not met.
  - The `<what>` text in the outcome error: `URL contains '/search'`,
    `element {...} appears`, `element {...} is gone`, `element {...} has value 'X'`.
  - `ExecutedStep`'s `healed`, `healed_element` and `error` default to False, None and "".
    Callers can still pass all seven fields by keyword (bs_harness does).
  - `StepExecutor` is `runtime_checkable`.
  - A healed step's `error` is the result's error, which is normally "".
- **Shortcuts taken**: a `url_change` with no `urlContains` is not compared with the URL
  from before the step. This stops working if BrightSky stores bare `url_change` outcomes
  that mean "the URL must change". Recording the URL in `before` and comparing in `after`
  would fix it.
- **Review fixes**:
  - Round 1, floor guard (`# type: ignore[misc]` in `test_executed_step_is_frozen`): the
    assignment is now `setattr(executed, "outcome", "failed")` inside the same
    `pytest.raises(dataclasses.FrozenInstanceError)`, so the test checks the same thing
    without a suppression. Re-run after the fix: `test_brightsky_executor.py` 46 passed,
    `test_step_hooks.py` 21 passed, `stepper/tests/unit/` 2067 passed, build and lint exit 0,
    and `git diff 7d099e7 -- stepper` has no `type: ignore`, `noqa`, skip or xfail lines.
- **For later tickets**:
  - Ticket 13: attach the hook with `runner.add_hook("web", ExpectationHook(mapped.expectations))`
    and pass `RecordingResolver(resolver)` as the runner's resolver. Then call
    `executed_steps(mapped, results, recording.tiers)`.
  - Replacement runners also run `before`, with the replacement step's description. A heal
    that changes the description has no expectation in the replacement runner, but the
    outer runner's `after` still checks the healed result.
  - A passed step whose first resolve missed (a retry found it) reports `tier=None`,
    `matched=True`.

## Review findings (round 1, floor guard)

floor guard: the diff weakens the bar instead of meeting it
suppress: stepper/tests/unit/test_brightsky_executor.py: executed.outcome = "failed"  # type: ignore[misc]
if a finding is intended, the ticket needs a line like: Floor: allow <category>
