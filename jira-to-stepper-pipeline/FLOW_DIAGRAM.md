# Jira-to-Stepper Pipeline — Flow Diagram

## Happy Path: Jira Ticket → Running Workflow → Report

```
POST /run-stepper-pipeline { jiraKey, stepperRepoPath }
        │
        ▼
[StepperOrchestrator]  creates workflowId, initialises artifact store
        │
        ▼
[StoryPlannerAgent]  ──── Jira API ────► ticket { summary, description, ACs }
        │                                         │
        │            Claude API ◄── ticket + action registry context
        │                    │
        ▼                    ▼
  plan.json saved    { targetSite, existingActionsReused,
  to artifact store    newActionsNeeded, skipCodeGen }
        │
        ├─ skipCodeGen = true ──────────────────────────────────────────┐
        │                                                               │
        ▼  skipCodeGen = false                                          │
[CodeGenOrchestrator]                                                   │
  ├──► [ConfigWriterAgent]  → poms/<site>/config.py (if needed)        │
  ├──► [PomWriterAgent]     → poms/<site>/pages/<page>.py              │
  └──► [GlueWriterAgent]    → stepper/sites/<site>/pages/<action>.py   │
        │                                                               │
        ▼                                                               │
[ArchitectureValidatorAgent]                                            │
  reads generated files, runs 5 rule checks                            │
        │                                                               │
        ├─ passed = false, retryCount < 3 ─────────────────────────────┤
        │   violations → CodeGenOrchestrator (targeted retry)          │
        │   retryCount++                                                │
        │                                                               │
        ├─ passed = false, retryCount >= 3                             │
        │   └──► status = NEEDS_HUMAN  (pipeline halts here)           │
        │                                                               │
        ▼  passed = true ◄─────────────────────────────────────────────┘
[WorkflowBuilderAgent]
  all action names + test scenarios + example JSONs ──► Claude API
        │
        ▼
  stepper/sites/<site>/workflows/<jiraKey>.json written
        │
        ▼
[WorkflowRunnerAgent]
  spawn: python stepper/main.py --workflow <path> --headless
        │
        ├─ exit code != 0 or timeout
        │   └──► run-result { passed: false, partial stepResults }
        │
        ▼  exit code 0
  read stepper/report.json → run-result { passed, stepResults[], screenshots }
        │
        ▼
[ReportAnalystAgent]
  run-result + plan.json ACs ──► Claude API
        │
        ├──► final-report-{jiraKey}.md  (saved locally)
        └──► jiraService.addComment()   (Jira comment posted)
        │
        ▼
  workflowId status = "completed"
```

---

## Retry Loop: Validation Failure Path

```
[ArchitectureValidatorAgent]  passed = false
        │
        ▼  violations[]
[CodeGenOrchestrator]  retry N  (max 3)
  │
  ├── violation in POM file  ──► [PomWriterAgent]   re-run with violations injected
  ├── violation in Glue file ──► [GlueWriterAgent]  re-run with violations injected
  └── violation in Config    ──► [ConfigWriterAgent] re-run with violations injected
        │
        ▼
[ArchitectureValidatorAgent]  re-check
        │
        ├─ passed = true  ──► continue pipeline
        └─ passed = false ──► retryCount++ → loop or NEEDS_HUMAN
```

---

## Skip Code Gen Path (All Actions Already Exist)

```
[StoryPlannerAgent]
  plan.json: skipCodeGen = true
        │
        │  (CodeGenOrchestrator and ArchitectureValidatorAgent are skipped)
        │
        ▼
[WorkflowBuilderAgent]
  uses only existingActionsReused[]
        │
        ▼
  ... (normal Runner → Analyst path)
```

---

## Component Legend

| Component | Role in this pipeline |
|---|---|
| `StepperOrchestrator` | Coordinates the 6-agent chain; manages workflowId and artifact store |
| `StoryPlannerAgent` | Fetches Jira ticket; classifies site + action requirements |
| `CodeGenOrchestrator` | Spawns and sequences the 3 code-writing sub-agents |
| `PomWriterAgent` | Writes cfg-list-compliant POM methods |
| `GlueWriterAgent` | Writes resolver-injecting glue action files |
| `ConfigWriterAgent` | Updates site config if new settings are needed |
| `ArchitectureValidatorAgent` | Enforces 5 stepper architecture rules; drives retry loop |
| `WorkflowBuilderAgent` | Produces stepper workflow JSON from validated action names |
| `WorkflowRunnerAgent` | Shells out to `python stepper/main.py`; reads `report.json` |
| `ReportAnalystAgent` | Maps step results to Jira ACs; posts Jira comment |
| `artifact store` | `AgentResultStore` (existing temp-repo) — shared read/write between all agents |
| `stepper engine` | Black box subprocess — `playwright-stepper-framework/stepper/main.py` |
