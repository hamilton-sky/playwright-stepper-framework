# Jira-to-Stepper Pipeline — Architecture Proposal

## Problem Statement

Converting a Jira user story into a running stepper workflow requires: understanding what the story tests, knowing which stepper actions exist, generating architecture-compliant Python code across 3 layers (POM, Glue, Config), and then composing a valid workflow JSON. Each of these steps has strict rules (the three-layer contract) that are easy to violate when generating code with an LLM. The result must be executable, not just syntactically correct.

## Proposed Solution

A sequential 6-agent pipeline (with a 3-sub-agent code generation stage) built on top of the existing `temp-repo` multi-agent infrastructure. Rules are injected as LLM context from the existing `.claude/rules/*.md` files — no reimplementation of rules as static analyzers. The stepper engine is treated as a black box: the pipeline writes files into it and invokes it as a subprocess.

## Component Diagram

```
POST /run-stepper-pipeline
        │
        ▼
StepperOrchestrator
  (extends MultiAgentOrchestrator)
        │
        ├─[1]──► StoryPlannerAgent
        │         ├── jiraService (existing)
        │         ├── action-registry.context
        │         └── Claude API → plan.json
        │
        ├─[2]──► CodeGenOrchestrator
        │         ├── [2a] ConfigWriterAgent → poms/<site>/config.py
        │         ├── [2b] PomWriterAgent   → poms/<site>/pages/*.py
        │         └── [2c] GlueWriterAgent  → stepper/sites/<site>/pages/*.py
        │                 (all write to playwright-stepper-framework/ via filesystem)
        │
        ├─[3]──► ArchitectureValidatorAgent
        │         ├── reads generated files
        │         ├── LLM-based rule checks (5 rules)
        │         ├── violations → retry CodeGenOrchestrator (max 3x)
        │         └── validation-report.json
        │
        ├─[4]──► WorkflowBuilderAgent
        │         ├── plan.json + validated action names
        │         ├── Claude API → workflow JSON
        │         └── stepper/sites/<site>/workflows/<jiraKey>.json
        │
        ├─[5]──► WorkflowRunnerAgent
        │         ├── spawn: python stepper/main.py --workflow <path>
        │         ├── reads: stepper/report.json
        │         └── run-result.json
        │
        └─[6]──► ReportAnalystAgent
                  ├── run-result.json + plan.json ACs
                  ├── Claude API → final-report-{jiraKey}.md
                  └── jiraService.addComment()
```

## Data Flow

```
Jira ticket (QA-42)
      │
      ▼ StoryPlannerAgent
plan.json
  { targetSite, existingActionsReused, newActionsNeeded, skipCodeGen }
      │
      ▼ CodeGenOrchestrator (if !skipCodeGen)
Generated files in playwright-stepper-framework/
  poms/<site>/pages/<page>.py
  stepper/sites/<site>/pages/<action>.py
      │
      ▼ ArchitectureValidatorAgent
validation-report.json   ←──── retry loop (max 3x) ────┐
  { passed, violations }  ────────────────────────────► CodeGenOrchestrator
      │ (passed)
      ▼ WorkflowBuilderAgent
stepper/sites/<site>/workflows/QA-42.json
      │
      ▼ WorkflowRunnerAgent
run-result.json
  { passed, stepResults[], reportPath }
      │
      ▼ ReportAnalystAgent
final-report-QA-42.md  +  Jira comment
```

## Key Design Decisions

### Decision 1: Extend temp-repo, don't rebuild
- **Options**: A) Extend temp-repo infrastructure, B) Build fresh in brightsky-ai backend, C) Standalone Python script
- **Chosen**: A
- **Rationale**: BaseAgent, AgentRegistry, MultiAgentOrchestrator, AgentResultStore, and jiraService are already proven and production-quality. The registry pattern means new agents don't require orchestrator changes. Option B duplicates infrastructure. Option C loses the registry, artifact store, and API layer.

### Decision 2: Rules as LLM context, not static analyzers
- **Options**: A) Parse Python AST to check rules, B) Inject `.claude/rules/*.md` as LLM prompt context, C) Regex-based checks
- **Chosen**: B (with C as a fast pre-filter for obvious violations like import statements)
- **Rationale**: Rules are already written in human-readable form in the rule files. Maintaining a parallel AST-based implementation would double the maintenance burden. LLM-based checking handles nuance (e.g., "is this a fill call?") that regex misses.

### Decision 3: Sub-agents ordered Config → POM → Glue
- **Rationale**: Config must exist before POM references settings. POM method signatures must exist before Glue wraps them. Reversing this order would require the sub-agents to make assumptions about interfaces that don't exist yet.

### Decision 4: WorkflowRunnerAgent uses a child process, not a Python binding
- **Options**: A) `child_process.spawn` calling `python stepper/main.py`, B) Port stepper to TypeScript, C) REST API wrapper around stepper
- **Chosen**: A
- **Rationale**: The stepper is a self-contained Python engine with its own report format. Porting it duplicates a large, tested codebase. A REST wrapper adds a deployment dependency. Shelling out is the minimal integration point and keeps the two repos independent.

### Decision 5: Retry loop at orchestrator level, not inside the validator
- **Rationale**: The validator should report, not orchestrate. The CodeGenOrchestrator owns the retry decision because it knows which sub-agent produced the violated file and can target the retry precisely.

## API / Interface Changes

**New endpoint:**
```
POST /run-stepper-pipeline
Body: StepperPipelineInput { jiraKey, stepperRepoPath, headless? }
Response: { status, workflowId }
```

**New types in `stepperPipeline.types.ts`:**
- `StepperPipelineInput`
- `PlanJson` (+ `TestScenario`, `NewActionSpec`, `NewPomMethodSpec`)
- `ValidationReport` (+ `ArchitectureViolation`)
- `RunResult` (+ `StepResult`)

**Existing `multiAgent.types.ts`:** Add `NEEDS_HUMAN` to `WorkflowStage` enum if not already present.

## Migration / Backwards Compatibility

- Existing `/run-multi-agent` endpoint and all existing agents are untouched
- New agents are added to `config/agents.json` with `enabled: true` only in the new `StepperOrchestrator` — they are not injected into the existing `MultiAgentOrchestrator` flow
- `AgentRegistry` is a singleton — new self-registering agents are visible globally, but only `StepperOrchestrator` runs them

## Risks

- **LLM rule violations at high rate**: If the LLM consistently violates architecture rules, 3-retry limit may not be enough. Mitigation: inject example of the *correct* pattern alongside the violation in each retry; use temperature 0 for code generation.
- **Stepper Python environment not found**: `python` may not be in PATH on the temp-repo server. Mitigation: make the Python executable path configurable in settings.
- **Generated code has subtle runtime bugs that pass static checks**: Validation catches structural violations, not logic errors. Mitigation: the workflow run itself is the integration test — failures surface here.
- **Large Jira tickets overwhelming planner context**: Very detailed tickets with long descriptions may push past context limits. Mitigation: truncate description to 4,000 chars and always include acceptance criteria in full.
