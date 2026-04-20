# LLM Transpiler — Edge Cases

## Category 1: Schema Grounding Failures

### EC-1.1: Registry empty at extraction time
- **Trigger**: `ActionSchemaExtractor.extract()` called before `register_all_sites()`
- **Current behavior**: would extract only engine-level actions (navigate, click, etc.)
- **Expected behavior**: warn in log; `ClaudePlanner` falls back to generic prompt
- **Handled in**: Phase 2 — extraction is always called after `register_all_sites()`

### EC-1.2: LLM ignores injected schema, uses generic action names
- **Trigger**: Claude returns `{"action": "click"}` despite schema listing `ol_ensure_login`
- **Current behavior**: `ActionRegistry.create("click")` raises `ValueError`
- **Expected behavior**: `PlanValidator.validate()` catches this before runner fires,
  raises `PlanValidationError` with clear message listing valid action names
- **Handled in**: Phase 3

### EC-1.3: LLM returns single object instead of array
- **Trigger**: Claude hallucinates `{"action": "ol_ensure_login"}` (not in a list)
- **Current behavior**: `json.loads()` succeeds but `[_dict_to_step(s) for s in steps_raw]` fails
- **Expected behavior**: `ClaudePlanner.plan()` wraps single objects in a list before parsing
- **Handled in**: Phase 2 — add guard: `if isinstance(steps_raw, dict): steps_raw = [steps_raw]`

---

## Category 2: Dry-Run Gate Failures

### EC-2.1: Non-interactive stdin (CI pipeline)
- **Trigger**: `--dry-run` used in a script that pipes stdin
- **Current behavior**: `input()` hangs or raises `EOFError`
- **Expected behavior**: detect non-tty, default to `N`, print "Non-interactive — aborting."
- **Handled in**: Phase 4 — check `sys.stdin.isatty()` before `input()`

### EC-2.2: `stepper/artifacts/` directory doesn't exist
- **Trigger**: fresh clone, artifacts dir never created
- **Expected behavior**: `Path(...).mkdir(parents=True, exist_ok=True)` before writing
- **Handled in**: Phase 4

### EC-2.3: `--dry-run` with `--workflow` on a large workflow
- **Trigger**: author wants to review an existing JSON workflow before running
- **Expected behavior**: `JsonFilePlanner.plan()` runs, validation runs, gate prompts
- **Handled in**: Phase 4 — gate runs after any `planner.plan()` call when `dry_run=True`

---

## Category 3: Validation Edge Cases

### EC-3.1: Step has empty description
- **Trigger**: LLM omits or blanks the `description` field
- **Expected behavior**: `PlanValidator` flags it; error message says which step index
- **Handled in**: Phase 3

### EC-3.2: Multiple bad steps
- **Trigger**: LLM hallucinates 3 action names in a 5-step plan
- **Expected behavior**: validator collects ALL errors, raises once with full list
- **Handled in**: Phase 3 — accumulate errors, raise at end

---

## Known Limitations
- Schema extraction reads `_registry` (internal dict) directly — if `ActionRegistry`
  is refactored to hide this dict, the extractor needs updating.
- `ClaudePlanner` grounding improves correctness but doesn't guarantee it;
  the validator is the hard gate, not the prompt.
- Self-healing (re-planning on execution failure) is out of scope for this plan —
  tracked separately in `plans/self-healing/`.

---

## Category 4: Prompt Attention Degradation (future risk)

### EC-4.1: Schema prompt block grows too large as sites are added
- **Trigger**: Registry reaches 30+ actions across 5+ sites; `to_prompt_block()` emits
  a long list and Claude's attention over the full action vocabulary degrades — it
  reverts to using generic or early-listed action names
- **Observed signal**: `PlanValidator` rejection rate climbs as more sites are added
- **Expected fix**: site-scoped injection — detect the target site from the task string
  (e.g. "OpenLibrary" → filter schema to `ol_*` actions only) before building the prompt
- **Handled in**: not in scope for this plan — add `ActionSchemaExtractor.extract_for_site(registry, site_prefix)`
  as a follow-up when registry exceeds ~25 actions
- **Interim mitigation**: order actions in `to_prompt_block()` by most-recently-used
  (recency bias) so the most relevant actions appear first in the prompt
