# Data-Driven Workflow — Flow Diagram

## Happy Path: ol_data_driven.json

```
[ol_data_driven.json]
        │
        │  step: "load_test_data"
        │  extra.path: "poms/openLibrary/data/testdata.json"
        ▼
[LoadTestDataAction._execute]  ← NEW
        │  reads JSON array (4 rows)
        │  context.collected_items = [{query,max_year,limit,...}, ...]
        ▼
[ol_data_driven.json]
        │
        │  step: "for_each_item"
        ▼
[ForEachItemAction._execute]  ← existing, unchanged
        │  for idx, row in enumerate(context.collected_items):
        │    subs = {
        │      "item.query":    row["query"],
        │      "item.max_year": row["max_year"],
        │      "item.limit":    row["limit"],
        │      "item_url":      row.get("url",""),
        │      "index":         str(idx+1),
        │    }
        │
        │  sub-step: "run_workflow"
        │  extra.path: "stepper/sites/openlibrary/workflows/ol_search_and_add.json"
        │  extra.vars: {query:{{item.query}}, max_year:{{item.max_year}}, limit:{{item.limit}}}
        ▼
[RunWorkflowAction._execute]  ← existing, unchanged
        │  loads ol_search_and_add.json
        │  merges vars (overrides workflow-level variables)
        │  runs sub-steps via self._run_steps(sub_steps, context)
        ▼
[ol_* glue actions + POMs]  ← existing, unchanged
        │  ol_ensure_login → ol_clear_reading_list
        │  → ol_collect_books → ol_add_to_shelf → ol_assert_count
        ▼
[StepResult: passed]  ──► next for_each_item iteration
```

## Error / Fallback Paths

```
[LoadTestDataAction]
        │  file not found OR not a list
        └─► StepResult(status="failed", error="load_test_data: ...")
                │
                └─► StepRunner: step fails, workflow stops
                    (unless continue_on_failure=true)

[ForEachItemAction — one row fails]
        │  sub-step raises or returns failed
        └─► logs error, takes error screenshot
            continues with next row  (stop_on_failure=False)
```

## Component Legend

| Symbol | Meaning |
|--------|---------|
| `[LoadTestDataAction]` | New engine action — reads JSON file into context |
| `[ForEachItemAction]` | Existing — iterates collected_items, spreads `{{item.*}}` |
| `[RunWorkflowAction]` | Existing — loads and runs a sub-workflow JSON |
| `[ol_* actions]` | Existing OpenLibrary glue actions — unchanged |
