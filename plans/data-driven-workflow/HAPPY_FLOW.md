# Data-Driven Workflow — Happy Flow

## Overview
A single workflow run reads `testdata.json` (4 entries) and executes the full
OpenLibrary search-and-add journey once per entry — clearing the reading list,
searching for books, adding them to the shelf, and asserting the count — all
without any manual workflow duplication.

## Step-by-Step Happy Flow

### Step 1: load_test_data
- **Action**: `load_test_data`
- **Stepper does**: opens `poms/openLibrary/data/testdata.json`, parses the array,
  sets `context.collected_items` to the 4 row dicts
- **Browser state**: no page interaction

### Step 2: for_each_item (row 1 — Dune)
- **Action**: `for_each_item`
- **Stepper does**: takes row 0 `{query:"Dune", max_year:1980, limit:5, expected_count:5}`,
  exposes `{{item.query}}=Dune`, `{{item.max_year}}=1980`, `{{item.limit}}=5`
- **Sub-step**: `run_workflow` → `ol_search_and_add.json` with those vars merged in
- **Browser state**: OL reading list cleared, 5 Dune books added, count asserted

### Step 2 repeats for rows 2–4 (Foundation, 1984, Pride and Prejudice)

## End State
4 complete search-and-add cycles executed. Each iteration left the reading list
in a clean state (clear → add N books → assert count == N).

## Success Indicators
- [ ] `load_test_data` step passes with `context.collected_items` length == 4
- [ ] `for_each_item` completes 4 iterations without aborting
- [ ] Each `run_workflow` sub-call passes (ol_search_and_add succeeds per row)
- [ ] No unhandled exceptions in stepper output
