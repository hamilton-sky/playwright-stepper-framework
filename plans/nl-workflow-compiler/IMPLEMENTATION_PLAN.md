# NL Workflow Compiler — Implementation Plan

## Overview

Adds a `--compile` mode to `stepper/main.py`. The user writes plain-language intent; the system opens a browser, snapshots the ARIA accessibility tree, sends intent + tree + action registry to AI (Groq → Gemini → Claude), receives a complete workflow JSON with cfg lists, and saves it. All execution after compile is deterministic — no AI tokens at runtime.

## Layer Architecture

```
CLI (main.py --compile)
        │
        ▼
NLCompiler (stepper/engine/compiler/compiler.py)
        │   1. launch browser → navigate to site base URL
        │   2. page.accessibility.snapshot() → ARIA tree
        │   3. ActionSchemaExtractor.extract(registry) → action list
        │   4. PromptBuilder → system + user prompts
        │   5. AIService.chat(task_type="compile") → raw JSON string
        │   6. OutputParser → validate + write workflow JSON
        ▼
Saved workflow JSON  (stepper/sites/<site>/workflows/<name>.json)
        │
        ▼  (later, separate run)
Existing runner + resolver cascade + self-healing (unchanged)
```

---

## Phases

### Phase 1: AIService — add compile task type (trivial)
**Layer:** Engine / AI
**Files:**
- `stepper/engine/ai/service.py` — add `"compile"` key to `_TASK_CHAINS` and `_MAX_TOKENS`

**Details:**
Add to `_TASK_CHAINS`: `"compile": ["groq", "gemini", "claude"]`
Add to `_MAX_TOKENS`: `"compile": 3000`
No other changes to `service.py`.

**Verify:** `python -c "from engine.ai.service import AIService; print('ok')"`

---

### Phase 2: Compiler module — NLCompiler, PromptBuilder, OutputParser
**Layer:** Engine
**Files:**
- `stepper/engine/compiler/__init__.py` — empty
- `stepper/engine/compiler/compiler.py` — `NLCompiler` class
- `stepper/engine/compiler/prompt_builder.py` — `PromptBuilder` class
- `stepper/engine/compiler/output_parser.py` — `OutputParser` class

**Details:**

**PromptBuilder:**
```
system_prompt = """You are a browser automation workflow compiler.

Given:
  - A list of available actions and their descriptions
  - An ARIA accessibility tree snapshot of the target page
  - A plain-language automation intent

Return a JSON array of steps. Each step must use only actions from the provided list.

cfg list rules (MUST follow):
- Every element that will be clicked or filled needs a cfg list
- Each cfg dict must include "priority" (lower = tried first)
- Prefer: role+name (priority 10), label (priority 20), placeholder (priority 30),
          id (priority 50), css (priority 60)
- Include at least 2 fallback strategies per element

Step schema:
{
  "action": "<action_name>",           // must be in the action list
  "description": "short label",
  "params": { ... },                   // action-specific params
  "element": [                         // cfg list — required for click/fill actions
    {"role": "button", "name": "...", "priority": 10},
    {"css": "...", "priority": 60}
  ]
}

Return ONLY valid JSON array. No markdown. No explanation.
"""

user_prompt = f"""
Available actions:
{action_schema_block}

ARIA tree of target page:
{aria_tree_json}

Intent: {user_intent}
"""
```

**NLCompiler:**
```python
class NLCompiler:
    async def compile(self, intent, site_name, output_path, headless=True) -> Path:
        # 1. Get site base URL from config
        # 2. Launch browser, navigate, snapshot ARIA
        # 3. Build registry + schema
        # 4. Call AIService compile
        # 5. Parse + validate
        # 6. Write JSON
        # 7. Return output path
```

**OutputParser:**
- Parse JSON array from AI response
- Validate each step's `action` is in registry (warn, don't drop)
- Return list of step dicts ready to write as workflow JSON

**Verify:** `python -c "from engine.compiler.compiler import NLCompiler; print('ok')"`

---

### Phase 3: CLI — add --compile flag to main.py
**Layer:** Engine / CLI
**Files:**
- `stepper/main.py` — add `--compile`, `--site`, `--output` args + `compile_workflow()` async function

**Details:**
```
python stepper/main.py --compile "log in, add item to cart, checkout" --site saucedemo
python stepper/main.py --compile "search for Dune, add to reading list" --site openlibrary --output my_flow.json
```

New args:
- `--compile TEXT` — natural language intent (activates compile mode)
- `--site NAME` — required with --compile; determines base URL and output dir
- `--output PATH` — optional; default: `stepper/sites/<site>/workflows/compiled.json`

New async function `compile_workflow(args)` that:
1. Builds registry (same as `run()` but no browser context yet — NLCompiler handles its own)
2. Instantiates `NLCompiler`
3. Calls `compiler.compile(intent, site, output, headless=not args.show)`
4. Prints: `Workflow saved to: <path>` + `Run it with: python stepper/main.py --workflow <path>`

**Verify:**
```bash
python stepper/main.py --compile "log in as standard_user, add Sauce Labs Backpack to cart, view cart" --site saucedemo --show
# Should create stepper/sites/saucedemo/workflows/compiled.json
# Then:
python stepper/main.py --workflow stepper/sites/saucedemo/workflows/compiled.json --show
```

---

### Phase 4: Site config helpers — resolve base URL per site
**Layer:** Engine / Config
**Files:**
- `stepper/engine/compiler/site_registry.py` — `SITE_CONFIGS` dict mapping site name → base URL

**Details:**
```python
SITE_CONFIGS = {
    "saucedemo":   {"base_url": "https://www.saucedemo.com"},
    "openlibrary": {"base_url": "https://openlibrary.org"},
    "phptravels":  {"base_url": "https://www.phptravels.net"},
}
```

The compiler looks up base URL from here rather than importing site-specific config modules (avoids glue → engine dependency inversion).

**Verify:** Already covered by Phase 3 verify.

---

## Prerequisites
- `GROQ_API_KEY` or `ANTHROPIC_API_KEY` set in `.env`
- Playwright installed and browsers downloaded

## Key Decisions
- Compile uses AIService (not ClaudePlanner directly) so Groq runs first — cheaper
- ARIA tree not full DOM — compact, already structured with role/name/label
- Output is standard workflow JSON — runs with existing `--workflow` flag unchanged
- Compiler has its own browser context — does not reuse the run() browser lifecycle
