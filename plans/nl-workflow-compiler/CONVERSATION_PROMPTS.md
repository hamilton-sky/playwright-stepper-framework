# NL Workflow Compiler — Conversation Guide

Split into 3 conversations. Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: Compiler Engine (Phases 1–2)

**Prompt to paste:**
```
Implement NL Workflow Compiler Conversation 1 (Phases 1–2) from plans/nl-workflow-compiler/IMPLEMENTATION_PLAN.md.

Conversation 1 is DONE when:
- engine/ai/service.py has "compile" in _TASK_CHAINS (["groq","gemini","claude"]) and _MAX_TOKENS (3000)
- stepper/engine/compiler/ module exists with compiler.py, prompt_builder.py, output_parser.py, __init__.py
- NLCompiler.compile(intent, site_name, output_path, headless) is implemented as async
- PromptBuilder builds system prompt with cfg list rules and user prompt with action schema + ARIA tree + intent
- OutputParser validates action names against registry and returns list of step dicts
- ARIA snapshot is taken with page.accessibility.snapshot() after navigating to base URL
- Snapshot is truncated at 200 nodes with a warning log if exceeded

Phase 1 details (service.py):
- Add "compile": ["groq", "gemini", "claude"] to _TASK_CHAINS
- Add "compile": 3000 to _MAX_TOKENS
- No other changes

Phase 2 details (compiler module):
- NLCompiler launches its own playwright browser (do not reuse main.py browser lifecycle)
- It receives an already-built action_registry and calls ActionSchemaExtractor.extract(registry) for the schema
- base_url is passed in at construction (not resolved inside the class — caller provides it)
- OutputParser warns (does not drop) steps with unrecognized action names
- OutputParser strips markdown fences from AI response before JSON parsing

Do NOT touch main.py, site configs, or any exam tests yet.

Verify: python -c "from engine.compiler.compiler import NLCompiler; print('ok')"

After done, update plans/nl-workflow-compiler/PROGRESS.md phases 1–2 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `stepper/engine/compiler/` module importable; AIService has compile chain.
**Files touched:** `stepper/engine/ai/service.py`, `stepper/engine/compiler/__init__.py`, `stepper/engine/compiler/compiler.py`, `stepper/engine/compiler/prompt_builder.py`, `stepper/engine/compiler/output_parser.py`

---

## Conversation 2: CLI Integration (Phases 3–4)

**Prompt to paste:**
```
Implement NL Workflow Compiler Conversation 2 (Phases 3–4) from plans/nl-workflow-compiler/IMPLEMENTATION_PLAN.md.
Conversation 1 is DONE: stepper/engine/compiler/ module exists with NLCompiler, PromptBuilder, OutputParser. AIService has compile task type.

Scope:
Phase 3 — Add --compile, --site, --output args to main.py argparser.
  - Add a compile_workflow(args) async function (not inside run())
  - compile_workflow builds the action registry the same way run() does (call build_default_registry + register_all_sites)
  - compile_workflow instantiates NLCompiler, looks up base_url from SITE_CONFIGS, calls compiler.compile()
  - On success, print: "Workflow saved to: <path>" and "Run it with: python stepper/main.py --workflow <path>"
  - --compile is mutually exclusive with --workflow and --task (add argparse group or simple check)

Phase 4 — Add stepper/engine/compiler/site_registry.py with SITE_CONFIGS dict:
  SITE_CONFIGS = {
    "saucedemo":   {"base_url": "https://www.saucedemo.com"},
    "openlibrary": {"base_url": "https://openlibrary.org"},
    "phptravels":  {"base_url": "https://www.phptravels.net"},
  }
  NLCompiler reads base_url from this dict (caller passes it in, not imported inside compiler.py).

Do NOT touch any POM files, glue files, or exam tests.

Verify:
  python stepper/main.py --compile "log in as standard_user, add Sauce Labs Backpack to cart, view cart" --site saucedemo --show
  # Should open browser, snapshot ARIA, call AI, save compiled.json
  # Then verify the output runs:
  python stepper/main.py --workflow stepper/sites/saucedemo/workflows/compiled.json --show --heal 1

After done, update plans/nl-workflow-compiler/PROGRESS.md phases 3–4 to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
```

**Expected output:** `--compile` flag works end-to-end; compiled JSON saved and runnable.
**Files touched:** `stepper/main.py`, `stepper/engine/compiler/site_registry.py`

---

## Conversation 3: End-to-End Validation

**Prompt to paste:**
```
Implement NL Workflow Compiler Conversation 3 (End-to-End validation) from plans/nl-workflow-compiler/IMPLEMENTATION_PLAN.md.
Conversations 1–2 are DONE: --compile flag works, NLCompiler saves workflow JSON.

Scope:
1. Run a full compile + execute cycle for SauceDemo:
   python stepper/main.py --compile "log in as standard_user, sort products by price low to high, add Sauce Labs Backpack to cart, go to cart, checkout with first name Test last name User postal 12345" --site saucedemo --show
   Save the compiled JSON. Inspect it — fix any action name validation warnings.

2. Run the compiled workflow with healing enabled:
   python stepper/main.py --workflow stepper/sites/saucedemo/workflows/compiled.json --show --heal 2

3. If the compiled JSON has incorrect action names (unrecognized), update the AI system prompt in PromptBuilder to more clearly describe each registered action's params. Do NOT hardcode fixes — improve the prompt so future compiles are correct.

4. Run a second compile for OpenLibrary:
   python stepper/main.py --compile "search for Dune, open the first result, add to reading list" --site openlibrary --output plans/nl-workflow-compiler/test_ol_compiled.json --show

5. Verify both compiled JSONs are valid by running them with --workflow.

6. Add a short note to plans/nl-workflow-compiler/HAPPY_FLOW.md describing the actual steps produced in the SauceDemo compile (for documentation).

After done, update plans/nl-workflow-compiler/PROGRESS.md Conv 3 to DONE and overall Status to DONE.

If a compiled workflow fails and self-healing cannot fix it, diagnose whether:
  A) The action name is wrong (fix prompt)
  B) The cfg list is wrong (fix prompt guidance)
  C) The action params are wrong (fix prompt)
Do NOT patch the compiled JSON by hand — fix the compiler prompt.

If verification fails and the fix requires out-of-scope engine changes, stop and report.
```

**Expected output:** Two compiled workflows running successfully (with heal if needed); prompt refined.
**Files touched:** `stepper/engine/compiler/prompt_builder.py` (if prompt needs tuning), `plans/nl-workflow-compiler/HAPPY_FLOW.md`
