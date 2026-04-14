# Jira-to-Stepper Pipeline — Conversation Guide

Split into 4 conversations. Each produces buildable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: Foundation + StoryPlannerAgent (Phases 1-2)

**Prompt to paste:**
```
Implement Jira-to-Stepper Pipeline Conversation 1 (Phases 1-2) from strategy/jira-to-stepper-pipeline/IMPLEMENTATION_PLAN.md.

Scope:
- Phase 1: Create `src/types/stepperPipeline.types.ts` with all shared pipeline types (StepperPipelineInput, PlanJson, ValidationReport, RunResult, and supporting sub-types as defined in the plan).
  Create `src/context/stepper-rules.context.ts` — a loader that reads the rule files from the playwright-stepper-framework .claude/rules/ directory and returns their content as a string, keyed by rule name (pom-layer, glue-layer, three-layer-contract, etc.).
  Create `src/context/action-registry.context.ts` — a loader that reads site-actions.md and 2-3 example workflow JSON files from the stepper repo and returns them as LLM-ready context strings, filtered by site name.
  Create `src/orchestration/StepperOrchestrator.ts` — a skeleton class that extends MultiAgentOrchestrator (search for 'class MultiAgentOrchestrator' to find the base). Leave agent imports as TODO stubs for now.
  Update `config/agents.json` — add 6 placeholder agent entries (enabled: false) for: StoryPlannerAgent (order 1), CodeGenOrchestrator (order 2), ArchitectureValidatorAgent (order 3), WorkflowBuilderAgent (order 4), WorkflowRunnerAgent (order 5), ReportAnalystAgent (order 6).

- Phase 2: Create `src/agents/StoryPlannerAgent.ts` that extends BaseAgent (search for 'class BaseAgent' to find the base class pattern). It must:
  1. Accept StepperPipelineInput as input type.
  2. Fetch the Jira ticket using the existing jiraService (search for 'jiraService' to find it).
  3. Load action-registry.context for the target site.
  4. Call Claude (reuse the existing Claude client pattern in the repo) with the ticket + action registry context + 2 inline few-shot PlanJson examples.
  5. Parse the response into PlanJson and set skipCodeGen: true if newActionsNeeded is empty.
  6. Save plan.json to the artifact store (search for 'AgentResultStore' for the pattern).
  7. Register itself in agentRegistry (search for 'agentRegistry.register' for the self-registration pattern).

Do NOT implement CodeGenOrchestrator, sub-agents, or any agent beyond StoryPlannerAgent yet.
Verify: npm run build
After done, update strategy/jira-to-stepper-pipeline/PROGRESS.md phases 1-2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report. If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** Types file, 2 context loaders, orchestrator skeleton, StoryPlannerAgent, updated agents.json — all building cleanly.
**Files touched:** `src/types/stepperPipeline.types.ts`, `src/context/stepper-rules.context.ts`, `src/context/action-registry.context.ts`, `src/orchestration/StepperOrchestrator.ts`, `src/agents/StoryPlannerAgent.ts`, `config/agents.json`

---

## Conversation 2: CodeGenOrchestrator + Sub-Agents (Phase 3)

**Prompt to paste:**
```
Conversation 1 is DONE (Foundation types + context loaders + StoryPlannerAgent built and verified).

Implement Jira-to-Stepper Pipeline Conversation 2 (Phase 3) from strategy/jira-to-stepper-pipeline/IMPLEMENTATION_PLAN.md.

Scope:
- Phase 3: Create `src/agents/CodeGenOrchestrator.ts` that extends BaseAgent. It must:
  1. Read plan.json from the artifact store (produced by StoryPlannerAgent).
  2. If plan.skipCodeGen is true, return a no-op result immediately.
  3. Run sub-agents sequentially: ConfigWriterAgent → PomWriterAgent → GlueWriterAgent.
  4. Accept an optional `violations` array (from ArchitectureValidatorAgent retry) and pass it to the relevant sub-agent as additional context.
  5. Register itself in agentRegistry.

  Create `src/agents/sub-agents/ConfigWriterAgent.ts` — writes/updates poms/<site>/config.py only when plan.newActionsNeeded contains actions requiring new config settings. Injects stepper-rules context for the relevant site. Uses filesystem tools to write the file.

  Create `src/agents/sub-agents/PomWriterAgent.ts` — writes poms/<site>/pages/<page>.py for each entry in plan.newPomMethodsNeeded. Prompt context must include: pom-layer rules (from stepper-rules.context), the SharedBasePage source file content, 1-2 existing POM files from the same site as examples. Uses filesystem tools to write the file.

  Create `src/agents/sub-agents/GlueWriterAgent.ts` — writes stepper/sites/<site>/pages/<action>.py for each entry in plan.newActionsNeeded. Prompt context must include: glue-layer rules (from stepper-rules.context), 1-2 existing glue files from the same site as examples, the PomWriterAgent output (method signatures). Uses filesystem tools to write the file.

  All sub-agents must use the stepper repo path from StepperPipelineInput (search for 'stepperRepoPath' in stepperPipeline.types.ts).

Do NOT implement ArchitectureValidatorAgent or WorkflowBuilderAgent yet.
Verify: npm run build
After done, update strategy/jira-to-stepper-pipeline/PROGRESS.md phase 3 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report. If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** CodeGenOrchestrator + 3 sub-agents, all building cleanly, filesystem writes working.
**Files touched:** `src/agents/CodeGenOrchestrator.ts`, `src/agents/sub-agents/ConfigWriterAgent.ts`, `src/agents/sub-agents/PomWriterAgent.ts`, `src/agents/sub-agents/GlueWriterAgent.ts`

---

## Conversation 3: ArchitectureValidatorAgent + WorkflowBuilderAgent (Phases 4-5)

**Prompt to paste:**
```
Conversations 1-2 are DONE (Foundation + StoryPlannerAgent + CodeGenOrchestrator + sub-agents built and verified).

Implement Jira-to-Stepper Pipeline Conversation 3 (Phases 4-5) from strategy/jira-to-stepper-pipeline/IMPLEMENTATION_PLAN.md.

Scope:
- Phase 4: Create `src/agents/ArchitectureValidatorAgent.ts` that extends BaseAgent. It must:
  1. Read the list of files written by CodeGenOrchestrator from the artifact store.
  2. Read each file's content using filesystem tools.
  3. Run 5 rule checks against the content (inject the rule text from stepper-rules.context as LLM context for each check):
     - three-layer-contract: no POM file imports from stepper/sites/
     - cfg-list-rule: every fill() or click() call references a cfg list variable, not a raw string
     - resolver-injection: every POM constructor call in glue files includes page=page and resolver=resolver
     - glue-rules: no page.locator() with a direct CSS string in glue files; no hardcoded credential strings
     - action-registration: every new action name appears in an ActionRegistry.register() call
  4. Produce ValidationReport and save it to the artifact store.
  5. If passed is false and retryCount < 3: call CodeGenOrchestrator.execute() again, passing the violations array and incrementing retryCount.
  6. If passed is false and retryCount >= 3: set workflow status to NEEDS_HUMAN (search for workflow status constants in multiAgent.types.ts).
  7. Register itself in agentRegistry.

- Phase 5: Create `src/agents/WorkflowBuilderAgent.ts` that extends BaseAgent. It must:
  1. Read plan.json from the artifact store.
  2. Collect all action names: plan.existingActionsReused + plan.newActionsNeeded[].name.
  3. Call Claude with: all action names, test scenarios from plan, 2-3 example workflow JSONs (from action-registry.context), Jira ticket summary.
  4. Parse the response into stepper workflow JSON format: { name, variables, steps[] }.
  5. Hoist any value that appears in more than one step's extra block into the variables section.
  6. Write the file to stepper/sites/<site>/workflows/<jiraKey>.json using filesystem tools.
  7. Register itself in agentRegistry.

Do NOT implement WorkflowRunnerAgent or ReportAnalystAgent yet.
Verify: npm run build
After done, update strategy/jira-to-stepper-pipeline/PROGRESS.md phases 4-5 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report. If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** Validator with retry loop + WorkflowBuilder writing valid JSON, all building cleanly.
**Files touched:** `src/agents/ArchitectureValidatorAgent.ts`, `src/agents/WorkflowBuilderAgent.ts`

---

## Conversation 4: WorkflowRunnerAgent + ReportAnalystAgent + Full Wiring (Phases 6-7)

**Prompt to paste:**
```
Conversations 1-3 are DONE (Foundation + StoryPlanner + CodeGen + Validator + WorkflowBuilder built and verified).

Implement Jira-to-Stepper Pipeline Conversation 4 (Phases 6-7) from strategy/jira-to-stepper-pipeline/IMPLEMENTATION_PLAN.md.

Scope:
- Phase 6: Create `src/agents/WorkflowRunnerAgent.ts` that extends BaseAgent. It must:
  1. Read the workflow JSON path written by WorkflowBuilderAgent from the artifact store.
  2. Spawn a child process: python stepper/main.py --workflow <path> [--headless if input.headless is true], with cwd set to stepperRepoPath from the pipeline input.
  3. Stream stdout lines to the artifact log in real time.
  4. On process exit, read stepper/report.json from the stepper repo (and stepper/reports/summary/all_tests_summary.json if it exists).
  5. Produce run-result.json: { passed, stepResults[], reportPath } and save to artifact store.
  6. Register itself in agentRegistry.

- Phase 7: Create `src/agents/ReportAnalystAgent.ts` that extends the existing ReportGeneratorAgent (search for 'class ReportGeneratorAgent' to find the base). It must:
  1. Read run-result.json and plan.json from the artifact store.
  2. Extract acceptance criteria from plan.json (sourced from the original Jira ticket).
  3. Map each acceptance criterion to pass/fail based on the step results.
  4. Produce final-report-{jiraKey}.md with: executive summary, AC pass/fail table, failed step details (error + screenshot path), recommendations.
  5. Post the summary as a Jira comment using the existing jiraService (search for 'addComment' or similar in jiraService).
  6. Register itself in agentRegistry.

  Wire up StepperOrchestrator.ts:
  - Replace TODO import stubs with real imports for all 6 agents (search for 'TODO stubs' comments added in Conv 1).
  - Ensure agents.json has all 6 agents set to enabled: true with correct order (1-6).

  Add a new API endpoint POST /run-stepper-pipeline to server.ts that accepts StepperPipelineInput and delegates to StepperOrchestrator (follow the same pattern as the existing POST /run-multi-agent endpoint, search for 'run-multi-agent' to find it).

Verify: npm run build + run a smoke test: POST /run-stepper-pipeline with a real Jira key and the stepper repo path.
After done, update strategy/jira-to-stepper-pipeline/PROGRESS.md phases 6-7 to DONE and overall Status to COMPLETE.

If verification fails and the fix requires out-of-scope changes, stop and report. If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** Full end-to-end pipeline running: Jira ticket → plan → code → validate → workflow JSON → stepper run → report → Jira comment.
**Files touched:** `src/agents/WorkflowRunnerAgent.ts`, `src/agents/ReportAnalystAgent.ts`, `src/orchestration/StepperOrchestrator.ts` (wiring), `config/agents.json` (final), `src/server.ts` (new endpoint)
