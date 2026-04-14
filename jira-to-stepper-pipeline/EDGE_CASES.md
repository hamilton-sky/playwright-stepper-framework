# Jira-to-Stepper Pipeline — Edge Cases

## Category 1: Story Planner Failures

### EC-1.1: Jira ticket has no acceptance criteria
- **Trigger**: Ticket description is minimal; no "Acceptance Criteria" section
- **Expected behavior**: Planner generates test scenarios from the description + summary only; plan.json includes a `warning: "no_acceptance_criteria"` flag
- **Handled in**: Phase 2 / Conv 1

### EC-1.2: Target site cannot be determined
- **Trigger**: Ticket mentions a site not in the stepper (e.g., "Amazon cart checkout")
- **Expected behavior**: Planner sets `targetSite: "unknown"` and `skipCodeGen: true`; ReportAnalystAgent flags this in the report with recommendation to scaffold a new site first
- **Handled in**: Phase 2 / Conv 1

### EC-1.3: All needed actions already exist
- **Trigger**: Ticket maps entirely to existing actions
- **Expected behavior**: `plan.json.skipCodeGen: true` → CodeGenOrchestrator returns no-op; pipeline jumps directly to WorkflowBuilderAgent
- **Handled in**: Phase 2 / Conv 1

---

## Category 2: Code Generation Failures

### EC-2.1: Generated POM uses raw CSS for a fill/click (cfg list rule violation)
- **Trigger**: LLM generates `driver.fill("#genre-select", value)` instead of `_resolve_and_fill_any`
- **Expected behavior**: ArchitectureValidatorAgent detects violation, feeds it back to PomWriterAgent with the specific line and rule; PomWriterAgent regenerates that method
- **Max retries**: 3 before NEEDS_HUMAN escalation
- **Handled in**: Phase 4 / Conv 3

### EC-2.2: Glue file missing resolver injection
- **Trigger**: LLM writes `GenrePage(driver, settings.base_url)` without `page=page, resolver=resolver`
- **Expected behavior**: Validator catches it, GlueWriterAgent regenerates with the violation message + glue-layer rule injected
- **Handled in**: Phase 4 / Conv 3

### EC-2.3: Reversed dependency (POM imports from stepper/sites/)
- **Trigger**: LLM adds `from stepper.sites.openlibrary.pages import ...` in a POM file
- **Expected behavior**: Validator catches import statement pattern, flags it, PomWriterAgent regenerates
- **Handled in**: Phase 4 / Conv 3

### EC-2.4: 3 retries exhausted, validation still failing
- **Trigger**: LLM consistently cannot satisfy a rule (e.g., ambiguous requirement)
- **Expected behavior**: Workflow status set to NEEDS_HUMAN; partial artifacts saved; report explains which rules failed and what was attempted
- **Handled in**: Phase 4 / Conv 3

### EC-2.5: New site required (site not yet scaffolded)
- **Trigger**: Ticket targets a site that has no `poms/<site>/` or `stepper/sites/<site>/` directory
- **Expected behavior**: PomWriterAgent first creates site scaffold (base_page.py, config.py, pages/ dir); then proceeds with the specific method
- **Handled in**: Phase 3 / Conv 2

---

## Category 3: Workflow Builder Failures

### EC-3.1: Action name mismatch (plan name ≠ registered name)
- **Trigger**: LLM generates action `ol_filter_genre` but GlueWriterAgent registered it as `ol_filter_by_genre`
- **Expected behavior**: WorkflowBuilderAgent reads the actual registered action name from the generated glue file before building the JSON (source of truth = the `ActionRegistry.register(` call in the file)
- **Handled in**: Phase 5 / Conv 3

### EC-3.2: Workflow JSON fails stepper schema validation
- **Trigger**: WorkflowBuilderAgent produces JSON missing required fields (e.g., no `action` key on a step)
- **Expected behavior**: WorkflowBuilderAgent validates JSON structure before writing; retries generation once if invalid
- **Handled in**: Phase 5 / Conv 3

---

## Category 4: Workflow Run Failures

### EC-4.1: Python process exits non-zero
- **Trigger**: Stepper throws an unhandled exception during run
- **Expected behavior**: WorkflowRunnerAgent captures stderr, saves it to the artifact log, marks run as `passed: false`; pipeline continues to ReportAnalystAgent with partial results
- **Handled in**: Phase 6 / Conv 4

### EC-4.2: `stepper/report.json` not found after run
- **Trigger**: Stepper crashed before writing its report
- **Expected behavior**: WorkflowRunnerAgent uses process exit code + captured stdout as the run result; marks all steps as unknown
- **Handled in**: Phase 6 / Conv 4

### EC-4.3: Stepper times out
- **Trigger**: Run takes longer than configured timeout (default: 5 min)
- **Expected behavior**: Child process is killed; partial report read; pipeline marks as `passed: false` with timeout reason
- **Handled in**: Phase 6 / Conv 4

---

## Category 5: Report + Jira Failures

### EC-5.1: Jira API call fails when posting comment
- **Trigger**: Network error or invalid API token
- **Expected behavior**: Report is still saved locally; error is logged; pipeline reports success with a warning about the missed Jira comment
- **Handled in**: Phase 7 / Conv 4

### EC-5.2: Some acceptance criteria cannot be mapped to step results
- **Trigger**: AC is about a feature not tested in the generated workflow
- **Expected behavior**: Report marks unmapped ACs as "NOT COVERED" and recommends extending the workflow
- **Handled in**: Phase 7 / Conv 4

---

## Known Limitations

- New site scaffolding creates the directory structure but does not generate a full working site — human review is expected before running a workflow against a brand-new site
- Multi-site workflows (e.g., login on site A, verify on site B) are out of scope for this pipeline iteration
- The validator uses LLM-based rule checking, not AST parsing — complex generated code patterns may occasionally produce false positives
