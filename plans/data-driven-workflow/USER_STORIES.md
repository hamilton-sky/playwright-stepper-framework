# Data-Driven Workflow — User Stories

## Context
OpenLibrary test data lives in `poms/openLibrary/data/testdata.json` as a list of
search scenarios (query, max_year, limit, expected_count). Currently the only way
to run the same workflow with different inputs is to duplicate JSON files or
hardcode variables. This feature adds a `load_test_data` engine action that loads
any JSON array into `context.collected_items`, enabling the existing
`for_each_item` + `run_workflow` combo to drive a sub-workflow once per data row.

---

## Stories

### Story 1.1: Load test data from file
**As a** test author, **I want** to point a workflow step at a JSON data file,
**so that** subsequent steps can iterate over each row without duplicating workflow files.

**Acceptance Criteria:**
- [ ] `load_test_data` action reads a JSON file (path from `extra.path`)
- [ ] Entries are stored in `context.collected_items`
- [ ] Both relative and absolute paths are accepted
- [ ] If the file doesn't exist the step fails with a clear error message

**Edge Cases:**
- File path is missing from `extra` → fail with descriptive error
- JSON file contains an object instead of an array → fail with descriptive error
- Empty array → step passes, subsequent `for_each_item` is a no-op

---

### Story 1.2: Data-driven sub-workflow iteration
**As a** test author, **I want** to run a sub-workflow once per data row,
**so that** I can validate multiple search scenarios in one workflow run.

**Acceptance Criteria:**
- [ ] `for_each_item` exposes row fields as `{{item.query}}`, `{{item.limit}}`, etc.
- [ ] `run_workflow` receives those values via its `vars` dict
- [ ] Each iteration is independent — a failure in one row does not abort the others

**Edge Cases:**
- Data row missing a key that the sub-workflow references → substitution leaves `{{item.missing}}` as-is (existing behaviour)
- Sub-workflow path is relative → resolved from cwd (existing `run_workflow` behaviour)
