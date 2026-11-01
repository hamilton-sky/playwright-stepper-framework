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

Work started at commit `68be132d6bc8b7fe8f66421d84ec62f574a440eb`. Test-first commits `ead77b4` (round 0) and `cfd5660` (round 1 review fixes).

- **Built**:
  - `stepper/brightsky/executor.py`: `EngineExecutor(page, resolver, *, ai_service=None, max_heal_attempts=3)` and `PipelineExecutor()`, both after `executed_steps`. The module docstring's "ticket 13" line now describes them.
  - `stepper/tests/unit/test_brightsky_executors.py` (new, 19 tests after round 1).
- **Proof** (round 1, fresh runs after the last edit): `test_brightsky_executors.py` gives `19 passed`; `stepper/tests/unit/` gives `2096 passed`; Build exit 0; Lint exit 0; acceptance unchanged at `85 passed, 76 failed` (all 06/07 modules). At `cfd5660` the four new tests failed for the right reason: the navigate reply healed the step (`['heal'] != ['heal','heal','heal_big']`), the extra-step reply clicked 3 times, the pipeline runner's healer was still the unwrapped one, and the site-naming temp dir did not raise.
- **Proof** (round 0, kept for the record; counts were 14 and 2091 then):
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
- **Shortcuts taken**: `PipelineExecutor` wraps the healer by assigning `built.runner._healer`, a private StepRunner attribute, because `build_pipeline`/`build_healer` (stepper/main.py, outside Touches) offer no seam. It breaks if StepRunner renames the attribute; a `healer_wrapper` or `healer=` argument on `build_pipeline` would be the upgrade, worth it once a second caller needs it.
- **Review fixes** (round 1):
  1. major, off-site heals: both executors now wrap their healer in `_ElementOnlyHealer` (executor.py). A reply must be exactly one step of the failed step's own action with a non-empty element, else `HealingError` (the heal loop counts it as a failed attempt and climbs the rungs). The step that runs is `dataclasses.replace(failed_step, element=reply.element)`, so a reply cannot change the URL, value, extra or add steps either. The schema is still the full registry's, as the ticket says; enforcement is after the reply. Tests: `test_engine_rejects_a_heal_reply_that_navigates_off_site` (AI replies navigate to evil.example: `page.goto` never called, `["heal","heal","heal_big"]`, step failed, not healed), `test_engine_rejects_a_heal_reply_that_adds_steps`, `test_engine_accepts_a_heal_reply_that_only_changes_the_element` (tier `cheap`), `test_pipeline_limits_the_runners_healer_to_element_changes`.
  2. minor: `EngineExecutor.__init__` passes `ai_service` straight to AiHealer; the unused `AIService` import is gone. The no-keys test still passes with `ai_service=None`.
  3. minor: `PipelineExecutor` now raises `RuntimeError` before `prepare_run` when `_extract_site` of the temp workflow path is not `"shared"` (a TMPDIR inside `sites/<name>`), so no site's settings or storage state can reach a verify run. Test: `test_pipeline_refuses_a_temp_dir_that_names_a_site` (nothing in the pipeline is called, the temp dir is removed).
- **For later tickets**:
  - Ticket 06: a heal reply that is not one same-action step with an element is a failed heal attempt, so a healed step's `healed_element["healed"]` is always just an element cfg on the original step.
  - Ticket 06: `PipelineExecutor()` takes no arguments. `EngineExecutor(page, resolver, ai_service=...)` matches `bs_harness.engine_world`. Both return `executed_steps(...)`, one per BrightSky step, so a healed step's `tier` is `healed_element["tier"]` (`embed_direct`, `cheap` or `big`), or `healer` when there is no healed_element (a visual-bridge injection).
  - A `DomainNotReadyError` from `PipelineExecutor` propagates as `stepper.bootstrap.session.DomainNotReadyError`.

## Review findings (round 1, pair review)

Scope of review: range 68be132d..a5791c96 (END equals HEAD, so no later commits are left out). I read the ticket blob at the base commit, which has an empty Answer, and the diff with the tasks folder left out. The Answer did not reach me. Both Done when commands pass when I run them: test_brightsky_executors.py gives 14 passed, and stepper/tests/unit/ gives 2091 passed. `git status` is clean. I left no files behind. My one probe ran from a stdin heredoc and wrote nothing.

Inputs I probed as a hostile caller:
- mapped.steps sent through the temp workflow.json. The round trip is safe: there is no `include` key, no variables, so no `{{}}` substitution happens, and dict_to_step_config gives back the same fields.
- `headless`
- `ai_service` and `max_heal_attempts`. These are constructor arguments set by the caller, as the spec says.
- The temp dir path. The site comes out as "shared", so no storage state is written.
- The heal model's reply and the prompt it is built from. The prompt holds the step description and element from the backend, plus the page DOM.

QUALITY
1. major stepper/brightsky/executor.py: The heal loop lets a run go off-site, which skips the host check in mapping.py. Both executors give AiHealer the action schema of the whole registry. EngineExecutor does it with `ActionSchemaExtractor.extract(build_default_registry())`. PipelineExecutor does it through `build_healer(cfg, prepared.registry)`. That registry has 22 actions, including navigate, load_test_data, screenshot (whose filename comes from extra), ensure_login and parallel. AiHealer._parse accepts any of them, and StepRunner runs the replacement steps. So whoever controls the heal prompt (the BrightSky title or target text, or the page content) can make a verify run navigate to any URL, read local JSON files, or write screenshots. I confirmed this in memory: a mapped click step plus an AI reply of `[{"action":"navigate","url":"https://evil.example/steal"}]` gave `page.goto("https://evil.example/steal")` through EngineExecutor. The verdict is still `failed`, but the off-site visit and other side effects have already happened. The ticket is level 3 precisely because these executors "decide which pages a run visits". Fix: in both executors, limit the healer schema to the mapped step's own action (or to {click, fill}), or reject any replacement step whose action differs from the failed step's. PipelineExecutor needs this too, which means a seam in build_healer or build_pipeline. The ticket text says "schema from the same registry", so if the conductor wants that wording settled, send it to the architect.
2. minor stepper/brightsky/executor.py: In `EngineExecutor.__init__`, `ai_service if ai_service is not None else AIService()` repeats what AiHealer already does (`ai_service or AIService()`). Pass `ai_service` straight through.
3. minor stepper/brightsky/executor.py: The site comes from the temp path through `_extract_site`. If TMPDIR contains a `sites/<name>` segment, the run would load that site's settings and could use its storage_state path. Fix: put the temp file under a fixed site-neutral path, or say in a comment that the site is always "shared".

REVIEW: FAIL

Reviewed brightsky-verify ticket 13 over the range 68be132..a5791c9. a5791c9 is the newest commit that touches the ticket, and it is also HEAD, so there are no later commits left out of the review. I read the ticket at the base commit, where Answer is still empty, and never read its Answer. The ticket's Status hunk changes `open` to `resolved`. git status is clean, and the pytest runs I did used `-p no:cacheprovider`.

SPEC
- `python3 -m pytest stepper/tests/unit/test_brightsky_executors.py -q` passes, plus the EngineExecutor embed_direct heal test: MET (conductor). I read `test_engine_an_embed_direct_cfg_that_resolves_heals_with_no_ai_call`. It checks that the first resolve is for the stored `{"role":"link","name":"The Hobbit"}` with `strict is True`, then that the next resolve is for the found cfg, that the outcome is `failed` with `healed is True` and `tier == "embed_direct"`, and that `ai.task_types == []`. Both probes are monkeypatched by the `probes` fixture.
- Embed_direct miss goes `["heal","heal","heal_big"]` and ends `failed`/`healed=False`; `ai_service=None` with no keys and a no-cfg payload ends `failed`: MET (conductor). Both cases are in that same file: `test_engine_a_missing_cfg_and_missing_ai_replies_go_cheap_cheap_big` and `test_engine_without_an_ai_service_or_keys_leaves_a_no_cfg_step_failed`. The second one `delenv`s ANTHROPIC_API_KEY, GROQ_API_KEY and GEMINI_API_KEY. Those are the only keys `stepper/engine/ai/providers.py` reads.
- PipelineExecutor RunConfig, hook, close on raise, no temp file: MET (conductor). The four pipeline functions are monkeypatched in the same file, and so are `build_settings` and `build_resolver`. One test checks `max_heal_attempts == 3`, `use_heal_cache is False`, `strict_heal_order is True` and `headless` for both True and False. Other tests check that an ExpectationHook is attached on "web", that `close_all` runs when `execute_pipeline` raises, and that the temp file and its directory are gone afterwards.
- `python3 -m pytest stepper/tests/unit/ -q`: MET (conductor).
- scope: OK. The changed files are `stepper/brightsky/executor.py` and `stepper/tests/unit/test_brightsky_executors.py`, which are the files the ticket lists. The other changes are one appended line each in `plans/brightsky-verify/map.md` and `plans/brightsky-verify/learnings.md`, tagged (13). Those are the plan's standard append-only bookkeeping, which every ticket commits along with its code. Nothing in the diff touches ticket 05's hook, recording resolver or conversion, or ticket 06's backend or proposal work.
- test first: OK. ead77b4 adds the test file before the code. The conductor saw it fail before a5791c9, and it has to fail without the production change, because it imports `EngineExecutor` and `PipelineExecutor`, which did not exist then.

Acceptance check: I ran `python3 -m pytest plans/brightsky-verify/acceptance/test_accept_heal.py -q` myself, since it exercises EngineExecutor: 18 failed, 11 passed. All 18 failures are `ModuleNotFoundError: No module named 'stepper.brightsky.verify'`, a module that belongs to a ticket not built yet. None fails on behaviour this ticket delivers. The conductor's failing list is in `test_accept_verify_cli.py`, the CLI ticket.

The level stays at 3. The heal budget and the strict order are in the ticket's own text, so they are already covered.

REVIEW: PASS
