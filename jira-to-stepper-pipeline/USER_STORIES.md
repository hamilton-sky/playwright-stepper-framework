# Jira-to-Stepper Pipeline — User Stories

## Context

QA engineers and developers receive Jira user stories describing features to test. Today, converting those stories into runnable Playwright automation requires manual work across 3 layers (POM, Glue, Workflow JSON), deep knowledge of the stepper architecture rules, and manual execution. This pipeline automates the entire chain: from Jira ticket to executing workflow to final report — producing architecture-compliant code without human intervention.

## Stories

### Story 1.1: Automated Plan from Jira Ticket
**As a** QA engineer, **I want** to provide a Jira ticket key and receive a structured automation plan, **so that** I know exactly which stepper actions are needed and whether any new code must be written.

**Acceptance Criteria:**
- [ ] Given a Jira ticket key, the system fetches summary, description, and acceptance criteria
- [ ] The plan identifies the target site (openlibrary, saucedemo, phptravels)
- [ ] The plan lists which existing actions can be reused vs. which new ones must be created
- [ ] If all needed actions already exist, code generation is skipped
- [ ] Output is a structured `plan.json` artifact saved under `workflow-results/{workflowId}/`

**Edge Cases:**
- Jira ticket has no acceptance criteria → planner falls back to description only
- Target site cannot be determined → agent asks for clarification or defaults to "unknown" and flags it
- Jira ticket references a site not yet in the stepper → planner flags as "new site needed"

---

### Story 1.2: Architecture-Compliant Code Generation
**As a** QA engineer, **I want** the system to generate POM and Glue code that strictly follows the stepper architecture rules, **so that** the generated code passes validation without manual fixes.

**Acceptance Criteria:**
- [ ] POM files use cfg lists for all interactive elements (no plain CSS for fill/click)
- [ ] Glue files always pass `page=page, resolver=resolver` to POM constructors
- [ ] No reversed dependency direction (POMs never import from stepper/sites/)
- [ ] All new actions are registered in `ActionRegistry`
- [ ] Generated code compiles without syntax errors

**Edge Cases:**
- Generated code fails architecture validation → system retries up to 3 times with violation feedback
- After 3 retries validation still fails → workflow pauses and reports to user with specific violations
- New site required → agent creates the full site scaffold (base_page, config, pages dir)

---

### Story 1.3: Executable Workflow JSON from Plan
**As a** QA engineer, **I want** a valid stepper workflow JSON file produced automatically from the plan, **so that** I can run it immediately without hand-editing.

**Acceptance Criteria:**
- [ ] Workflow JSON contains `name`, `variables`, and `steps[]`
- [ ] Every `action` in steps matches a registered action name
- [ ] Repeated values across steps are hoisted to the `variables` block
- [ ] Workflow file is saved to `stepper/sites/<site>/workflows/<jiraKey>.json`

**Edge Cases:**
- Action names from plan don't exist after code gen → validator catches this before workflow build
- Plan has zero new actions (all reused) → workflow builder uses existing actions only, no code gen

---

### Story 1.4: Automated Workflow Execution and Report
**As a** QA engineer, **I want** the pipeline to run the generated workflow and produce a report mapped to the original Jira acceptance criteria, **so that** I know which criteria passed and which need attention.

**Acceptance Criteria:**
- [ ] Stepper workflow runs via `python stepper/main.py --workflow <path> --headless`
- [ ] Each acceptance criterion from the Jira ticket is mapped to pass/fail status
- [ ] Report includes failed step details (error message, screenshot path if available)
- [ ] Report is saved as `final-report-{jiraKey}.md`
- [ ] Jira ticket receives a comment with the report summary (via Jira API)

**Edge Cases:**
- Workflow run fails at step N → report captures partial results up to step N
- Jira API call fails → report is still saved locally, error logged but pipeline does not fail
- No screenshots available (headless without screenshot steps) → report notes this
