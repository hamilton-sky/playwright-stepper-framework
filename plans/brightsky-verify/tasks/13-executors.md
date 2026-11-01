# Run a mapped workflow: the browser-free EngineExecutor and the real PipelineExecutor

Type: task
Status: open
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
