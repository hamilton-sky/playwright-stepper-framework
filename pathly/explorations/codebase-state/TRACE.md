# Trace - codebase-state

## Scout Setup
Pathly explore tracing used four scouts in one parallel batch:

- Orientation scout: repository structure, entrypoints, docs, test layout, generated artifacts.
- Runtime scout: `stepper/main.py`, runner, registry/glue/POM boundary, healing cache.
- Generated-site scout: discovery output, generation conventions, `register.py`, workflow JSON contract.
- Docs/plans/tests scout: README, pytest surfaces, `.claude/skills`, planning state, dirty worktree.

## Repository Map
The repository has two visible product surfaces:

- `exam/`: exam-specific pytest flow and supporting docs.
- `stepper/`: JSON workflow runtime, engine, generated site actions, tests, reports, and artifacts.

The main framework layers are:

- `poms/`: pure page objects and shared resolver-aware interaction helpers.
- `stepper/engine/`: action registry, runner, page module/glue abstractions, resolver/healing/reporting support.
- `stepper/sites/<site>/`: site-specific glue actions, workflows, artifacts, and explicit `register.py`.
- `.claude/skills/`: local workflow skills for discovery, generation, testing, and validation.
- `plans/`: product/architecture plans; some are completed feature plans, some are aspirational roadmap docs.

The checkout also contains generated/runtime state:

- `.stepper/<site>/trace.json` and snapshots.
- `stepper/reports/`, `reports/allure-results/`, `artifacts/screenshots/`.
- `stepper/models/all-MiniLM-L6-v2/`.
- `.playwright-mcp/`.
- `playwright_stepper_framework.egg-info/`.

The orientation scout found `stepper/server/` and `stepper/ui/` referenced in `plans/UI_STACK_DECISION.md`, but both are absent in this checkout. Treat those as planned architecture, not current implementation.

## Runtime Path
`stepper/main.py` is the production startup path. It:

- Creates the `ActionRegistry`.
- Calls `register_all_sites()`.
- Creates `HealCache` from the selected site's artifacts path.
- Enables `AiHealer` only when `--heal` is requested and credentials exist.
- Builds `StepRunner`.
- Registers `RunWorkflowAction` after the runner exists so subflows can resolve correctly.

`stepper/engine/runner/step_runner.py` is the main execution engine. It:

- Evaluates `when` conditions.
- Records skipped steps.
- Resolves actions through the registry.
- Applies retries.
- Stops on failure unless `continue_on_failure` is set.
- Enters bounded healing only after normal execution fails.
- Uses cached healing before invoking AI.
- Runs healed replacement steps through a replacement runner with healer disabled to prevent recursive loops.

Runtime risks:

- `when` evaluation failures run the step anyway, which is permissive and can hide workflow condition errors.
- The healing path is complex enough that it needs dedicated tests; a normal happy-path workflow is not enough.
- `HealCache` keys are based on action, description, and element JSON, but not page/version state, so stale healed selectors can survive later UI drift.

## Registry, Glue, And POM Contract
The strongest implementation invariant is:

```text
workflow JSON step -> action registry lookup -> glue action -> POM method
```

The JSON workflow knows action names and data only. It must not know selectors or POM classes.

Critical rules confirmed by scouts:

- `ActionRegistry` is string-keyed by `action_name`.
- `PageModule.register` requires site actions to use the `site_` prefix.
- `GlueAction` constructs POMs with `page`, `resolver`, and `behaviour`.
- Site `register.py` files are the visibility gate. Without them, generated actions are invisible at runtime.
- POMs own selectors and interaction semantics.
- Interactive POM elements should be `Locator` objects.
- Read-only CSS strings can be acceptable for query/count paths.
- Workflows stay selector-free and action-centric.

This boundary is the core value of the codebase and should not be diluted.

## Discovery And Generation Contract
Discovery and generation are already aligned around a useful local-first pipeline:

```text
/discover-site
  -> .stepper/<site>/trace.json
  -> .stepper/<site>/snapshots/
  -> /generate-poms
  -> poms/<site>/...
  -> stepper/sites/<site>/pages/...
  -> stepper/sites/<site>/register.py
  -> stepper/sites/<site>/workflows/...
```

Important conventions:

- Discovery artifacts are site-scoped under `.stepper/<site>/`.
- Snapshots are saved eagerly after navigation states.
- Discovery prefers role/name style signals before CSS/XPath.
- Generation must create both POMs and glue.
- Generation must create site-level `register.py`.
- Workflow JSON should have one step per glue action and must not contain locator strings.

## Docs, Plans, And Validation State
The README is broadly consistent with the current two-surface split:

- Exam pytest path.
- Stepper JSON workflow path.

The validation surfaces are broader than the local `.claude/skills/test` guidance:

- `exam/tests/test_openlibrary_exam.py` covers the exam flow.
- `stepper/tests/test_workflow.py` covers Stepper workflow execution.
- `stepper/tests/unit/` covers resolver/healing/drift helpers.
- `.claude/skills/test/SKILL.md` currently points only to `pytest exam/ -v`, so it is incomplete if treated as whole-repo validation guidance.

Planning state:

- Some plan folders are complete, including `plans/discover-site-skill/PROGRESS.md` and `plans/claude-skills-architecture/PROGRESS.md`.
- `plans/STEPPER_MVP_PLAN.md` still describes v1.0 goals such as `/setup-site`, `/coverage-report`, packaging, and automatic skill/hook wiring.
- `plans/UI_STACK_DECISION.md` references `stepper/server` and `stepper/ui`, but those directories do not exist in this checkout.

So the plans are mixed: some are historical/completed, some are current architecture intent, and some are future roadmap.

## Worktree State
At the time of this exploration, `git status --short` showed:

```text
 M poms/openLibrary/pages/book_search_page.py
 M poms/openLibrary/pages/reading_list_page.py
?? pathly/
```

The `pathly/` directory is this exploration artifact.

The modified POM files appear to be intentional behavior work around OpenLibrary filtering/pagination:

- `book_search_page.py` adds query token matching, stopwords, title-link extraction, and result-title filtering.
- `reading_list_page.py` avoids treating a missing next-page link as an interaction failure.

Those POM edits are not part of this exploration and were not changed here.

## Verification
I attempted to run:

```powershell
pytest -q stepper/tests/unit
```

The command was interrupted before completion, so this exploration cannot claim a passing test result.

Git emitted warnings about denied access to `C:\Users\Yafit/.config/git/ignore`; status still returned usable output.
