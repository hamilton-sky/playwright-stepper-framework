# Jira-to-Stepper Pipeline — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | 1-2 | Foundation types + context loaders + StoryPlannerAgent | TODO | `npm run build` |
| 2 | 3 | CodeGenOrchestrator + PomWriterAgent + GlueWriterAgent + ConfigWriterAgent | TODO | `npm run build` |
| 3 | 4-5 | ArchitectureValidatorAgent + WorkflowBuilderAgent | TODO | `npm run build` |
| 4 | 6-7 | WorkflowRunnerAgent + ReportAnalystAgent + full wiring | TODO | `npm run build` + e2e test |

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Description | Conv | Status | Key Files |
|---|-------|-------------|------|--------|-----------|
| 1 | Foundation | Types, context loaders, orchestrator skeleton, agents.json | 1 | TODO | `stepperPipeline.types.ts`, `stepper-rules.context.ts`, `action-registry.context.ts`, `StepperOrchestrator.ts` |
| 2 | StoryPlannerAgent | Jira → plan.json with site + action classification | 1 | TODO | `StoryPlannerAgent.ts` |
| 3 | CodeGenOrchestrator | Sub-agent spawner + PomWriter + GlueWriter + ConfigWriter | 2 | TODO | `CodeGenOrchestrator.ts`, `sub-agents/PomWriterAgent.ts`, `sub-agents/GlueWriterAgent.ts`, `sub-agents/ConfigWriterAgent.ts` |
| 4 | ArchitectureValidatorAgent | 5-rule checker with retry loop back to CodeGen | 3 | TODO | `ArchitectureValidatorAgent.ts` |
| 5 | WorkflowBuilderAgent | Validated actions → stepper workflow JSON | 3 | TODO | `WorkflowBuilderAgent.ts` |
| 6 | WorkflowRunnerAgent | Python child process + report.json reader | 4 | TODO | `WorkflowRunnerAgent.ts` |
| 7 | ReportAnalystAgent | AC mapping + Jira comment + full pipeline wiring | 4 | TODO | `ReportAnalystAgent.ts`, `StepperOrchestrator.ts` (wiring), `config/agents.json` (final) |

## Prerequisites

- `temp-repo` builds successfully
- Jira API credentials in `.env`
- `playwright-stepper-framework` repo path configured
- Python + stepper deps installed

## Blocked By

- Nothing
