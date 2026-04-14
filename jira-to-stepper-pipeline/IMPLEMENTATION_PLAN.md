# Jira-to-Stepper Pipeline — Implementation Plan

## Overview

A 6-agent pipeline (with 3 sub-agents inside Agent 2) that converts a Jira user story into a running stepper workflow. Built on top of the existing `temp-repo` multi-agent infrastructure (`BaseAgent`, `AgentRegistry`, `MultiAgentOrchestrator`). The pipeline produces architecture-compliant POM + Glue code, a workflow JSON, executes it via the stepper engine, and returns a report mapped to the original Jira acceptance criteria.

## Architecture

```
temp-repo/src/
  agents/
    StoryPlannerAgent.ts          ← Phase 2
    CodeGenOrchestrator.ts        ← Phase 3 (spawns sub-agents)
      sub-agents/
        PomWriterAgent.ts         ← Phase 3
        GlueWriterAgent.ts        ← Phase 3
        ConfigWriterAgent.ts      ← Phase 3
    ArchitectureValidatorAgent.ts ← Phase 4
    WorkflowBuilderAgent.ts       ← Phase 5
    WorkflowRunnerAgent.ts        ← Phase 6
    ReportAnalystAgent.ts         ← Phase 7
  orchestration/
    StepperOrchestrator.ts        ← Phase 1 (extends MultiAgentOrchestrator)
  types/
    stepperPipeline.types.ts      ← Phase 1
  context/
    stepper-rules.context.ts      ← Phase 1 (loads architecture rules as LLM context)
    action-registry.context.ts    ← Phase 1 (loads known actions per site)
  config/
    agents.json                   ← Phase 1 (updated with new agents)
```

## Phases

---

### Phase 1: Foundation — Types, Context Loaders, Orchestrator Skeleton (Conv 1)

**Files:**
- `src/types/stepperPipeline.types.ts` — NEW: all shared types for the pipeline
- `src/context/stepper-rules.context.ts` — NEW: loads `.claude/rules/*.md` files as LLM context strings
- `src/context/action-registry.context.ts` — NEW: reads `site-actions.md` + example workflow JSONs per site
- `src/orchestration/StepperOrchestrator.ts` — NEW: extends `MultiAgentOrchestrator`, imports all 6 agents
- `config/agents.json` — MODIFIED: add 6 new agent entries in execution order

**Types to define in `stepperPipeline.types.ts`:**
```typescript
interface StepperPipelineInput {
  jiraKey: string;
  stepperRepoPath: string;  // path to playwright-stepper-framework
  headless?: boolean;
}

interface PlanJson {
  jiraKey: string;
  targetSite: string;
  testScenarios: TestScenario[];
  existingActionsReused: string[];
  newActionsNeeded: NewActionSpec[];
  newPomMethodsNeeded: NewPomMethodSpec[];
  skipCodeGen: boolean;  // true if all actions already exist
}

interface ValidationReport {
  passed: boolean;
  violations: ArchitectureViolation[];
  retryCount: number;
}

interface RunResult {
  passed: boolean;
  stepResults: StepResult[];
  reportPath: string;
}
```

**Verify:** `npm run build`

---

### Phase 2: StoryPlannerAgent (Conv 1)

**Files:**
- `src/agents/StoryPlannerAgent.ts` — NEW

**What it does:**
1. Fetches Jira ticket via `jiraService.ts` (already exists in temp-repo)
2. Loads `action-registry.context.ts` for the relevant site
3. Calls Claude with the ticket + action registry context
4. Prompt goal: classify `targetSite`, list `existingActionsReused`, list `newActionsNeeded` with params
5. Sets `skipCodeGen: true` if `newActionsNeeded.length === 0`
6. Saves `plan.json` to artifact store

**Prompt context injected:**
- Full Jira ticket (summary + description + acceptance criteria)
- `action-registry.context.ts` output (known actions per site, their params)
- 2 example `plan.json` outputs (few-shot)

**Verify:** `npm run build` + manual test with a real Jira key

---

### Phase 3: CodeGenOrchestrator + Sub-Agents (Conv 2)

**Files:**
- `src/agents/CodeGenOrchestrator.ts` — NEW (spawns sub-agents sequentially)
- `src/agents/sub-agents/PomWriterAgent.ts` — NEW
- `src/agents/sub-agents/GlueWriterAgent.ts` — NEW
- `src/agents/sub-agents/ConfigWriterAgent.ts` — NEW

**CodeGenOrchestrator:**
- Checks `plan.json.skipCodeGen` — if true, returns early with no-op result
- Runs sub-agents in order: Config → POM → Glue (config must exist before POM uses it)
- Passes violations from ArchitectureValidatorAgent (Phase 4) back into sub-agents on retry

**PomWriterAgent — prompt context injected:**
- `stepper-rules.context.ts` output for pom-layer rules
- Existing `SharedBasePage` source (so agent knows the helper methods)
- Existing POM files from the same site (pattern examples)
- `plan.json.newPomMethodsNeeded` spec

**GlueWriterAgent — prompt context injected:**
- `stepper-rules.context.ts` output for glue-layer rules
- Existing glue files from the same site (pattern examples)
- `plan.json.newActionsNeeded` spec + PomWriterAgent output (so it knows the method signatures)

**ConfigWriterAgent:**
- Only runs if `plan.json` identifies new config settings needed
- Updates `poms/<site>/config.py` with new defaults

**Verify:** `npm run build` + check generated files exist

---

### Phase 4: ArchitectureValidatorAgent (Conv 3)

**Files:**
- `src/agents/ArchitectureValidatorAgent.ts` — NEW

**What it does:**
1. Reads all files produced by CodeGenOrchestrator
2. Checks against 5 rules (from `.claude/rules/`):
   - `three-layer-contract`: no reversed imports (POM importing from stepper/sites/)
   - `cfg-list-rule`: every `fill()` / `click()` call uses a cfg list, not a raw string
   - `resolver-injection`: every POM constructor call has `page=page, resolver=resolver`
   - `glue-rules`: no `page.locator()` directly in glue, no hardcoded credentials
   - `action-registration`: all new action names registered in `ActionRegistry`
3. Produces `validation-report.json`
4. If `passed: false` AND `retryCount < 3` → feeds violations back to CodeGenOrchestrator for retry
5. If `passed: false` AND `retryCount >= 3` → escalates (sets workflow status to NEEDS_HUMAN)

**Verify:** `npm run build` + test with a deliberately broken generated file

---

### Phase 5: WorkflowBuilderAgent (Conv 3)

**Files:**
- `src/agents/WorkflowBuilderAgent.ts` — NEW

**What it does:**
1. Takes validated `plan.json` (existing + new actions)
2. Calls Claude with:
   - All action names (reused + newly generated)
   - Test scenarios from plan
   - 2-3 example workflow JSONs (few-shot via `action-registry.context.ts`)
3. Produces valid stepper workflow JSON:
   ```json
   { "name": "...", "variables": {...}, "steps": [ { "action", "description", "extra" } ] }
   ```
4. Hoists repeated values into `variables` block
5. Saves to `stepper/sites/<site>/workflows/<jiraKey>.json`

**Verify:** `npm run build` + validate JSON schema manually

---

### Phase 6: WorkflowRunnerAgent (Conv 4)

**Files:**
- `src/agents/WorkflowRunnerAgent.ts` — NEW

**What it does:**
1. Spawns `python stepper/main.py --workflow <path> [--headless]` as a child process
2. Streams stdout in real time (log to artifact store)
3. Waits for process exit
4. Reads `stepper/report.json` and `stepper/reports/summary/all_tests_summary.json`
5. Produces `run-result.json`:
   - `passed` (bool)
   - `stepResults[]` (action name, status, error if any, screenshot path)
   - `reportPath`

**Key implementation detail:**
```typescript
const proc = spawn('python', ['stepper/main.py', '--workflow', workflowPath, '--headless'], {
  cwd: settings.stepperRepoPath
});
```

**Verify:** `npm run build` + run with existing `ol_smoke_test.json`

---

### Phase 7: ReportAnalystAgent + Wiring (Conv 4)

**Files:**
- `src/agents/ReportAnalystAgent.ts` — NEW (extends existing `ReportGeneratorAgent`)
- `src/orchestration/StepperOrchestrator.ts` — MODIFIED: import and register all 6 agents
- `config/agents.json` — MODIFIED: final agent order + enabled flags

**ReportAnalystAgent — what it does:**
1. Reads `run-result.json` + original Jira acceptance criteria (from `plan.json`)
2. Maps each acceptance criterion to pass/fail based on step results
3. Produces `final-report-{jiraKey}.md` with:
   - Executive summary
   - AC-by-AC pass/fail table
   - Failed step details (error + screenshot path)
   - Recommendations (fix selector / add edge case / rerun)
4. Posts report summary as Jira comment via `jiraService.ts`

**Wiring in StepperOrchestrator:**
```typescript
import '../agents/StoryPlannerAgent.js';
import '../agents/CodeGenOrchestrator.js';
import '../agents/ArchitectureValidatorAgent.js';
import '../agents/WorkflowBuilderAgent.js';
import '../agents/WorkflowRunnerAgent.js';
import '../agents/ReportAnalystAgent.js';
```

**Verify:** `npm run build` + end-to-end test with a real Jira ticket

---

## Prerequisites

- `temp-repo` builds successfully (`npm run build` passes)
- Jira API credentials set in `.env` (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`)
- `playwright-stepper-framework` repo path configured in settings
- Python + stepper dependencies installed in `playwright-stepper-framework`
- Claude API key available (reuse existing `ANTHROPIC_API_KEY` or equivalent)

## Key Decisions

- **Extend temp-repo, don't start fresh** — `BaseAgent`, `AgentRegistry`, `MultiAgentOrchestrator`, and `AgentResultStore` are already production-quality. Replace agent content, keep the shell.
- **Rules as LLM context, not code** — Architecture rules from `.claude/rules/*.md` are injected as prompt context rather than implemented as static analyzers. Simpler to maintain; rules stay in sync with the source of truth.
- **Config → POM → Glue sub-agent order** — Config must exist before POM references it; POM method signatures must exist before Glue wraps them.
- **Retry loop is orchestrator-level** — Validator reports violations to CodeGenOrchestrator which re-runs sub-agents. Max 3 retries before human escalation.
- **Python child process for runner** — No reimplementation of the stepper engine; just shell out and read the existing `report.json`.
