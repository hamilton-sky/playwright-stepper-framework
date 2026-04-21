# NL Workflow Compiler Part 2 — Conversation Guide

Split into 3 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

**Prerequisite**: plans/nl-workflow-compiler/ Conversations 1–2 are DONE.
`stepper/engine/compiler/` exists with NLCompiler, PromptBuilder, OutputParser, site_registry.py.
AIService has "compile" task type. `--compile` flag works in main.py.

---

## Conversation 1: ARIAFilter + LiveLoopCompiler (Phases 1–2)

**Prompt to paste:**
```
Implement NL Workflow Compiler Part 2 Conversation 1 (Phases 1–2) from plans/nl-workflow-compiler-part-2/IMPLEMENTATION_PLAN.md.

Prerequisites DONE: stepper/engine/compiler/ has NLCompiler, PromptBuilder, OutputParser, site_registry.py. AIService has "compile" task type.

Scope:

Phase 1 — stepper/engine/compiler/aria_filter.py (NEW):
- ARIAFilter class with class methods: select_strategy(node_count), count_nodes(tree), apply(tree, strategy, page=None), to_compact_json(nodes)
- INTERACTIVE_ROLES set: button, textbox, link, combobox, checkbox, radio, menuitem, tab, option, searchbox, spinbutton, slider
- select_strategy: ≤50 → "full", 51–150 → "interactive_only", 151+ → "viewport_interactive"
- count_nodes: recursive count of all nodes in tree dict/list
- apply with strategy "full": serialize entire tree to flat node list
- apply with strategy "interactive_only": walk recursively, keep nodes whose role is in INTERACTIVE_ROLES, include name/label/placeholder/value fields if present
- apply with strategy "viewport_interactive": same as interactive_only, then filter by page.evaluate() bounding box — keep nodes visible in viewport. Falls back to interactive_only if evaluate fails or page is None
- If result after filtering is empty: fall back to "full" with a WARNING log
- to_compact_json: json.dumps with separators=(',',':') for minimal tokens

Phase 2 — stepper/engine/compiler/live_loop.py (NEW):
- LiveLoopCompiler class with:
  - MAX_PAGE_CYCLES = 10
  - MAX_STEPS_PER_PAGE = 15
  - STALL_THRESHOLD = 3
  - __init__(self, action_registry, ai_service=None)
  - async run(self, intent, base_url, output_path, headless=True, resolver=None) -> Path
- run() logic:
  1. Launch own playwright browser + context + page (do NOT reuse any passed-in page)
  2. Register page.on("framenavigated") handler that sets a _navigated flag
  3. page.goto(base_url)
  4. Loop up to MAX_PAGE_CYCLES:
     a. page.accessibility.snapshot() → raw tree
     b. count_nodes → select_strategy → ARIAFilter.apply()
     c. log: f"[LiveLoop] page {cycle}/{MAX_PAGE_CYCLES} url={page.url()} strategy={strategy} nodes={len(filtered)}"
     d. Build prompt: reuse PromptBuilder from engine.compiler.prompt_builder with completed_steps_summary added to user prompt (compact list of already-executed action names)
     e. AIService.chat(task_type="compile") → OutputParser.parse()
     f. If 0 steps returned → break (done)
     g. Cap steps at MAX_STEPS_PER_PAGE (log warning if exceeded)
     h. Reset _navigated = False
     i. StepRunner.run(page_steps) — build StepRunner with resolver, action_registry, a LoggingObserver
     j. Wait up to 2s for _navigated flag (asyncio.sleep(0.2) x 10 polls)
     k. If URL unchanged after execution: stall_count += 1; if stall_count >= STALL_THRESHOLD: log warning, break
     l. Add executed steps to all_steps list
  5. Write all_steps as JSON to output_path (create parent dirs)
  6. Return output_path
- On exception mid-loop: save partial steps to output_path with "_partial" suffix, re-raise

Do NOT touch main.py, AiHealer, or any POM/Glue files yet.

Verify:
  python -c "from engine.compiler.aria_filter import ARIAFilter; print(ARIAFilter.select_strategy(30), ARIAFilter.select_strategy(80), ARIAFilter.select_strategy(200))"
  # Should print: full interactive_only viewport_interactive
  python -c "from engine.compiler.live_loop import LiveLoopCompiler; print('ok')"

After done, update plans/nl-workflow-compiler-part-2/PROGRESS.md phases 1–2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** ARIAFilter importable with correct strategy selection; LiveLoopCompiler importable.
**Files touched:** `stepper/engine/compiler/aria_filter.py`, `stepper/engine/compiler/live_loop.py`

---

## Conversation 2: Enhanced AiHealer with Full Context (Phase 3)

**Prompt to paste:**
```
Implement NL Workflow Compiler Part 2 Conversation 2 (Phase 3) from plans/nl-workflow-compiler-part-2/IMPLEMENTATION_PLAN.md.
Conversation 1 is DONE: ARIAFilter and LiveLoopCompiler exist in stepper/engine/compiler/.

Scope:

Phase 3 — Enhance AiHealer with optional full workflow context:

In stepper/engine/healer/interfaces.py:
- Add optional keyword-only parameters to HealerStrategy.heal() ABC:
    all_steps: list | None = None
    current_index: int | None = None
    context_vars: dict | None = None
- Keep all existing positional params (step, error, dom) unchanged
- All new params are keyword-only (add * before them in the signature)
- Do NOT add aria_snapshot or completed_steps — DOMSnapshotCascade already covers DOM context

In stepper/engine/healer/ai_healer.py:
- Mirror the same optional keyword params in AiHealer.heal()
- When all_steps and current_index are BOTH provided:
    - Extract nearby_steps = all_steps[max(0, current_index-3) : current_index+4]
    - Serialize each as compact dict: {"action": s.action, "description": s.description} only
    - Add "workflow_context" key to user_msg JSON:
      {"current_index": N, "total_steps": M, "nearby_steps": [...], "context_vars": {...}}
- Do NOT add aria_snapshot key — dom.content from DOMSnapshotCascade already covers this
- Update _SYSTEM_TEMPLATE to add:
    "7. If workflow_context is provided, use nearby_steps to infer which page/phase the automation is in — this narrows which element to target."
- Keep the fast path (healed_cfg is not None) unchanged — it still returns immediately
- Log: "[AiHealer] heal with workflow context (step {current_index}/{total})" or "[AiHealer] heal (no context)"

Do NOT touch main.py, LiveLoopCompiler, ARIAFilter, or any POM/Glue files.
Do NOT break existing callers — all new params have None defaults, no existing call sites need to change.

Verify:
  python -c "
import inspect
from engine.healer.ai_healer import AiHealer
sig = inspect.signature(AiHealer.heal)
params = sig.parameters
assert 'all_steps' in params, 'missing all_steps'
assert 'current_index' in params, 'missing current_index'
assert 'context_vars' in params, 'missing context_vars'
assert 'aria_snapshot' not in params, 'aria_snapshot should NOT be present'
print('ok')
"
  All existing exam tests must still pass: pytest exam/ -x -q

After done, update plans/nl-workflow-compiler-part-2/PROGRESS.md phase 3 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** AiHealer.heal() accepts full context kwargs; existing tests still pass.
**Files touched:** `stepper/engine/healer/interfaces.py`, `stepper/engine/healer/ai_healer.py`

---

## Conversation 3: CLI --live flag + End-to-End (Phase 4)

**Prompt to paste:**
```
Implement NL Workflow Compiler Part 2 Conversation 3 (Phase 4) from plans/nl-workflow-compiler-part-2/IMPLEMENTATION_PLAN.md.
Conversations 1–2 are DONE: ARIAFilter, LiveLoopCompiler, enhanced AiHealer all exist.

Scope:

Phase 4 — Add --live CLI flag to main.py:

1. Add argparse argument --live TEXT (description: "Natural language intent for per-page live loop")
2. --live is mutually exclusive with --compile, --workflow, --task (add a check at top of main(), raise parser.error if combined)
3. --live requires --site (raise parser.error if --site missing)
4. Add async function live_workflow(args) to main.py:
   a. load_env() is already called by main(); do not call again
   b. load_settings_safe() → s
   c. build_default_registry() + register_all_sites() → action_registry
   d. SITE_CONFIGS from engine.compiler.site_registry → base_url
   e. Default output path: stepper/sites/<site>/workflows/live_<YYYYMMDD_HHMMSS>.json
      (use datetime.now().strftime("%Y%m%d_%H%M%S"))
   f. If args.output: use that path instead
   g. resolver = build_resolver(s.use_visual_ai)
   h. ai_service = AIService()
   i. compiler = LiveLoopCompiler(action_registry, ai_service=ai_service)
   j. output = await compiler.run(args.live, base_url, output_path, headless=not args.show, resolver=resolver)
   k. Print:
      f"Workflow saved to: {output}"
      f"Run deterministically: python stepper/main.py --workflow {output}"

5. In StepRunner call sites where --heal N > 0: wire the full context to AiHealer.
   In engine/runner/step_runner.py, find where healer.heal() is called.
   Pass: all_steps=steps, current_index=i, completed_steps=results[:i], context_vars=context

6. Run end-to-end test:
   python stepper/main.py --live "log in as standard_user, add Sauce Labs Backpack to cart, go to cart, start checkout with first name Test last name User postal 12345" --site saucedemo --show
   Verify: live_*.json created in stepper/sites/saucedemo/workflows/
   Then run: python stepper/main.py --workflow stepper/sites/saucedemo/workflows/live_*.json --show --heal 2

7. If the live loop produces incorrect action names (unrecognized), tune the PromptBuilder system prompt (in engine/compiler/prompt_builder.py) — do NOT patch the saved JSON by hand.

Do NOT touch POM or Glue files.

Verify:
  python stepper/main.py --live "log in as standard_user, add Sauce Labs Backpack to cart, view cart" --site saucedemo --show
  python stepper/main.py --workflow stepper/sites/saucedemo/workflows/live_*.json --show --heal 1

After done, update plans/nl-workflow-compiler-part-2/PROGRESS.md phase 4 and overall Status to DONE.

If verification fails and the fix requires out-of-scope engine changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `--live` runs per-page loop, saves JSON, saved JSON runs deterministically.
**Files touched:** `stepper/main.py`, `stepper/engine/runner/step_runner.py` (healer call site), optionally `stepper/engine/compiler/prompt_builder.py`
