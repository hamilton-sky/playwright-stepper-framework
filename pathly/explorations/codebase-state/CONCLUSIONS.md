# Conclusions - codebase-state

## Overall State
The codebase is coherent, but it is not cleanly packaged as a finished product yet.

The strongest shipped asset is the Stepper architecture itself:

```text
trace/snapshots -> generated POMs -> generated glue actions -> registered workflow actions -> JSON workflow execution
```

That chain is real in the codebase and backed by local skills, generated site folders, runtime registration, and tests. The architecture is not just documentation.

The weaker area is productization:

- Plans mention UI/server/package surfaces that are not present in this checkout.
- Validation guidance is split and partially stale.
- Generated/runtime artifacts live alongside source code.
- The worktree currently has uncommitted OpenLibrary POM changes.
- The local workflow is powerful, but still more framework/dev-tool than polished end-user app.

## What Works
- Clear POM/glue/workflow separation.
- Runtime action registration through site-level `register.py`.
- Selector-free JSON workflows.
- Site-scoped discovery artifacts under `.stepper/<site>/`.
- Existing generated examples across OpenLibrary, SauceDemo, phpTravels, and The Internet.
- Separate exam and Stepper validation suites.
- Local-first direction is consistent with the existing file-based workflow.

## Main Risks
- Registration mistakes cause runtime `Unknown action` failures.
- Healing behavior is powerful but complex; normal workflow tests will not catch all regressions.
- Heal cache keys may remain valid longer than the UI state they were created for.
- `when` condition failures currently run the step anyway, which can hide bad workflow expressions.
- `.claude/skills/test` under-represents the real validation surface.
- Planning docs can be mistaken for shipped code, especially around `stepper/server`, `stepper/ui`, packaging, and automatic wiring.

## Direct Recommendation
Do not start by building a big UI or packaging layer.

First stabilize the framework contract:

1. Update validation guidance so "test the repo" means both `stepper/tests` and `exam/tests`, with unit tests called out separately.
2. Add or confirm targeted tests around the healing path, `when` behavior, and action registration failures.
3. Decide whether the current OpenLibrary POM edits are intended, then test and commit them separately.
4. Mark roadmap-only docs clearly so `stepper/server` and `stepper/ui` are not confused with implemented surfaces.
5. Keep generated artifacts site-scoped, but decide which are source examples and which are local runtime output.

After that, the next good product step is the local manual-phase UI described in the plans: a browser UI that runs one phase at a time and shows the file artifacts. The current architecture supports that better than a one-button automation layer today.

## Build / Don't Build / Investigate More
Build:

- A cleaned validation contract and docs update.
- Focused runtime tests for registration, `when`, and healing.
- A small local phase-runner UI only after the validation contract is reliable.

Do not build yet:

- A broad SaaS/cloud product layer.
- A one-button orchestration layer.
- A packaging/release story that hides the current split between plans and shipped code.

Investigate more:

- Whether `HealCache` needs page/version invalidation.
- Whether `when` evaluation failures should fail closed instead of running the step.
- Whether generated artifacts should be separated into committed examples vs ignored runtime outputs.
- Whether `pyproject.toml` should package `stepper*` and skills, not only `poms*`, when productization begins.
