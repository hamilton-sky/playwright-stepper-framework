# Run a mapped workflow: the browser-free EngineExecutor and the real PipelineExecutor

Type: task
Status: resolved
Blocked by: 05
Test first: yes
Level: 3
Touches: stepper/brightsky/executor.py, stepper/tests/unit/test_brightsky_executors.py

Two `StepExecutor`s in `stepper/brightsky/executor.py` (new in ticket 05), both built from ticket 05's
pieces. Level 3: they set the heal budget (paid AI calls) and decide which pages a run
visits.

- **`EngineExecutor(page, resolver, *, ai_service=None, max_heal_attempts=3)`** runs the
  mapped steps without launching anything. It is also the public seam the spec names for
  testing the heal loop from outside (spec.md § Interfaces).
  - It builds a real `StepRunner(page=page, action_factory=<the real registry from
    build_default_registry()>, resolver=RecordingResolver(resolver), reporter=<a reporter
    that writes nothing>, healer=AiHealer(<schema from the same registry>,
    ai_service=ai_service), max_heal_attempts=max_heal_attempts, cache=None,
    strict_heal_order=True)` and adds the
    `ExpectationHook` with `add_hook("web", ...)`.
  - `ai_service=None` means a real `AIService()`, which with no keys set makes no request.
  - `execute(mapped, *, headless)` runs `mapped.steps` and returns `executed_steps(...)`.
    `headless` is ignored, since nothing is launched.
- **`PipelineExecutor()`**, `execute(mapped, *, headless)`:
  1. Writes `{"name": ..., "domain": "web", "steps": [...]}` to a
     `tempfile.TemporaryDirectory()`, with the steps as `dataclasses.asdict` of each
     StepConfig.
  2. Builds `RunConfig(workflow_path=..., headless=headless, max_heal_attempts=3,
     use_heal_cache=False, strict_heal_order=True)`. These two executors are the only
     place the strict heal order is switched on (brief, Decided).
  3. Wraps `build_resolver(build_settings(cfg).use_visual_ai)` in a `RecordingResolver`
     and calls `prepare_run(cfg, resolver=...)`.
  4. Calls `build_session_set`, then `build_pipeline`, then
     `pipeline.runner.add_hook("web", ExpectationHook(...))`, then `execute_pipeline`,
     and closes the sessions in `finally`, the same order as `stepper/main.py` `run()`.
  5. Imports the pipeline module lazily (`from stepper import main as pipeline`), so
     importing `executor` launches nothing.
  - A `DomainNotReadyError` (no browser) propagates. Nothing ran, so nothing is
    reported.

## Not in this ticket

- The hook, the recording resolver and the result conversion; ticket 05.
- Talking to the backend and building a proposal; ticket 06.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_executors.py -q` passes. Its
  `EngineExecutor` tests use a fake page, a resolver double that misses the stored
  `{"role": "link", "name": "The Hobbit"}` and finds `{"role": "link", "name": "The
  Hobbit (1937)", "css": "a.result"}`, an AI double that records `task_type`, and
  `DOMSnapshotCascade.capture` / `VisualBridge.check` monkeypatched. They show the
  resolver double asked for the stored target with `strict=True`, then the step coming
  back `failed` with `healed=True` and `tier == "embed_direct"` and no AI call when the
  payload carries the found cfg.
- In the same file, an `EngineExecutor` with an `embed_direct` payload whose cfg also
  misses and AI replies that miss records `["heal", "heal", "heal_big"]` and returns the
  step `failed` with `healed=False`; and one built with `ai_service=None` and every AI key
  `monkeypatch.delenv`'d returns the step `failed` for a payload with no cfg.
- In the same file, with `stepper.main`'s `prepare_run`, `build_session_set`,
  `build_pipeline` and `execute_pipeline` monkeypatched, `PipelineExecutor` passes a
  RunConfig with `max_heal_attempts == 3`, `use_heal_cache is False`,
  `strict_heal_order is True` and `headless` as asked, attaches an `ExpectationHook`, closes the sessions even when
  `execute_pipeline` raises, and leaves no temp file behind.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_executors.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("How a run is driven", "Heal cache off", "Heal order"),
  § Interfaces (`EngineExecutor`, the page probes)
- `stepper/main.py` `run()`, `prepare_run`, `build_pipeline`, `execute_pipeline`,
  `build_healer`
- `stepper/tests/unit/test_step_runner.py` fixtures and
  `stepper/tests/unit/test_ai_healer.py` `_ForbiddenAI` for the doubles

## Answer

Work started at commit `68be132d6bc8b7fe8f66421d84ec62f574a440eb`. Test-first commit `ead77b4`.

- **Built**:
  - `stepper/brightsky/executor.py`: `EngineExecutor(page, resolver, *, ai_service=None, max_heal_attempts=3)` and `PipelineExecutor()`, both after `executed_steps`. The module docstring's "ticket 13" line now describes them.
  - `stepper/tests/unit/test_brightsky_executors.py` (new, 14 tests).
- **Proof** (fresh runs after the last edit):
  - Test-first commit `ead77b4`: the file failed at collection with `ImportError: cannot import name 'EngineExecutor' from 'stepper.brightsky.executor'`.
  - `python3 -m pytest stepper/tests/unit/test_brightsky_executors.py -q`: `14 passed`.
    - Bullet 1: the resolver double's first call is `{"role": "link", "name": "The Hobbit"}` with `strict is True`. Its second call is the found cfg `{"role": "link", "name": "The Hobbit (1937)", "css": "a.result"}`. The step comes back `outcome == "failed"`, `healed is True`, `tier == "embed_direct"`, `matched is False`. The AI double records `[]`, capture is called once, and the locator is clicked once.
    - Bullet 2: with an embed_direct cfg that misses and AI replies that miss, the AI records `["heal", "heal", "heal_big"]`. Capture's `skip_direct` values are `[False, True, True, True]`, and the step is `failed` with `healed is False`. With `ai_service=None` and `ANTHROPIC_API_KEY`, `GROQ_API_KEY` and `GEMINI_API_KEY` delenv'd, a payload with no cfg gives a `failed` step, and the stored target is the only resolve. The log shows `all providers failed` for `heal`, `heal`, `heal_big`.
    - Bullet 3: with `stepper.main`'s `prepare_run`, `build_session_set`, `build_pipeline` and `execute_pipeline` patched (plus `build_settings` and `build_resolver`, so no settings or resolver are built), the RunConfig has `max_heal_attempts == 3`, `use_heal_cache is False`, `strict_heal_order is True`, and `headless is headless` (parametrized True and False). The call order is `build_resolver, prepare_run, build_session_set, build_pipeline, execute_pipeline`. The resolver passed is a `RecordingResolver`, and one `ExpectationHook` is added for `"web"`. `close_all` is awaited once on success and once when `execute_pipeline` raises (the error propagates). In both cases the workflow file and its temp dir no longer exist. The written workflow is `domain: "web"`, has a non-empty `name`, and its `steps` equal `[asdict(s) for s in mapped.steps]`.
    - Extra tests: a passing stored target gives `passed`, `matched`, tier `css`, and no capture. A `start_url` mismatch fails the step with no resolve, which shows the hook is attached in `EngineExecutor`. A `DomainNotReadyError` from `prepare_run` propagates, with no session set built, no close, and the temp dir gone. In a fresh subprocess, `import stepper.brightsky.executor` leaves `'stepper.main' not in sys.modules`. Both classes pass `isinstance(..., StepExecutor)`.
  - Bullet 4: `python3 -m pytest stepper/tests/unit/ -q` gave `2091 passed`. Build (`compileall`) exit 0, Lint (`main.py validate`) exit 0.
  - Acceptance, for reference: `85 passed, 76 failed`, up from 82/79. Every remaining failure is `No module named 'stepper.brightsky.verify'` or the CLI having no `brightsky` command, which belong to tickets 06 and 07.
- **Decisions**:
  - The reporter that writes nothing is `CompositeReporter([])`, an existing class, rather than a new null reporter.
  - `EngineExecutor` builds a new registry, `RecordingResolver`, `ExpectationHook` and `StepRunner` on every `execute`. One hook serves one run (ticket 05's note), and `tiers` stays per run. The `AIService` is built once, in `__init__`.
  - `EngineExecutor` passes no `hooks=` (no CAPTCHA probe or screenshot hook), `behaviour` is left to StepRunner's default `HumanBehaviour` (about 150 ms between steps), and there is no `screenshots_dir`. Only the ExpectationHook is added, as the ticket lists.
  - `PipelineExecutor` writes `workflow.json` inside `TemporaryDirectory(prefix="brightsky-verify-")`, with the name `"brightsky verify"`. `MappedWorkflow` has no name field. The whole run, including `close_all`, happens inside the `with`, so the directory is gone on every path.
  - `build_resolver` and `build_settings` are read off the lazily imported `stepper.main`, the same names `prepare_run` uses, so a test can patch them in one place.
  - `run()`'s `_tee_logs_to_run_file` and `allure_serve` are not used: the ticket's list is build_session_set → build_pipeline → add_hook → execute_pipeline → close in `finally`.
  - `_MAX_HEAL_ATTEMPTS = 3` is one module constant shared by both executors.
- **Shortcuts taken**: none.
- **For later tickets**:
  - Ticket 06: `PipelineExecutor()` takes no arguments. `EngineExecutor(page, resolver, ai_service=...)` matches `bs_harness.engine_world`. Both return `executed_steps(...)`, one per BrightSky step, so a healed step's `tier` is `healed_element["tier"]` (`embed_direct`, `cheap` or `big`), or `healer` when there is no healed_element (a visual-bridge injection).
  - A `DomainNotReadyError` from `PipelineExecutor` propagates as `stepper.bootstrap.session.DomainNotReadyError`.
