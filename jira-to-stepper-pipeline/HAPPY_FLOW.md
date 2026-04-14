# Jira-to-Stepper Pipeline — Happy Flow

## Overview

A developer posts a Jira ticket key to the pipeline API. The pipeline fetches the ticket, discovers that 2 of 4 needed actions already exist, generates 2 new POM methods + 2 glue files, validates them in one pass, builds a workflow JSON, runs it headlessly against the target site, and posts a report to Jira — all without human intervention.

## Step-by-Step Happy Flow

### Step 1: Trigger
- **User does**: POST `/run-stepper-pipeline` with `{ jiraKey: "QA-42", stepperRepoPath: "C:/...", headless: true }`
- **System does**: Creates a new `workflowId`, initialises artifact store, starts `StepperOrchestrator`
- **User sees**: `{ status: "running", workflowId: "uuid" }`

### Step 2: StoryPlannerAgent
- **System does**: Fetches QA-42 from Jira (summary + description + acceptance criteria). Loads action registry for OpenLibrary. Calls Claude to classify the ticket.
- **Output**: `plan.json` — target site: `openlibrary`, 2 existing actions reused (`ol_ensure_login`, `ol_collect_books`), 2 new actions needed (`ol_filter_by_genre`, `ol_assert_genre_label`), `skipCodeGen: false`

### Step 3: CodeGenOrchestrator → Sub-Agents
- **System does**:
  - ConfigWriterAgent: no new config needed → skips
  - PomWriterAgent: writes `poms/openLibrary/pages/search_page.py` — adds `filter_by_genre()` with a proper cfg list for the genre dropdown
  - GlueWriterAgent: writes `stepper/sites/openlibrary/pages/genre_filter_action.py` — `ol_filter_by_genre` and `ol_assert_genre_label` actions, both with `page=page, resolver=resolver`
- **Output**: 2 new files written to the stepper repo

### Step 4: ArchitectureValidatorAgent
- **System does**: Reads both generated files, runs 5 rule checks, all pass on first attempt
- **Output**: `validation-report.json` — `passed: true`, `violations: []`, `retryCount: 0`

### Step 5: WorkflowBuilderAgent
- **System does**: Combines 2 reused + 2 new actions. Calls Claude with all 4 action names + test scenarios + 2 example workflows. Hoists `query` into `variables` block.
- **Output**: `stepper/sites/openlibrary/workflows/QA-42.json` written with 6 steps

### Step 6: WorkflowRunnerAgent
- **System does**: Spawns `python stepper/main.py --workflow .../QA-42.json --headless`. Streams logs. Reads `stepper/report.json` on exit.
- **Output**: `run-result.json` — `passed: true`, all 6 steps passed, 5 screenshots captured

### Step 7: ReportAnalystAgent
- **System does**: Maps 3 acceptance criteria from QA-42 to step results (all pass). Generates `final-report-QA-42.md`. Posts summary to Jira as a comment.
- **Output**: Report saved, Jira comment posted

### Step 8: Pipeline Complete
- **User does**: GET `/workflow-status/{workflowId}`
- **User sees**: `{ status: "success", currentStage: "completed", ... }` + link to report file

## End State

The user has:
- A new POM method + glue action committed to the stepper repo
- A reusable workflow JSON for QA-42 in `stepper/sites/openlibrary/workflows/`
- A pass/fail report mapped to each acceptance criterion
- A Jira comment with the summary so the team can see it without leaving Jira

## Success Indicators
- [ ] `plan.json` correctly identifies existing vs. new actions
- [ ] Generated POM file passes cfg list rule (no raw CSS for fill/click)
- [ ] Validation passes on first attempt (no retries needed)
- [ ] Workflow JSON is valid stepper format and runnable
- [ ] All stepper steps pass
- [ ] Report AC table shows all criteria as passed
- [ ] Jira comment posted successfully
