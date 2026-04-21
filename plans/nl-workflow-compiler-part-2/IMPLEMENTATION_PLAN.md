# NL Workflow Compiler Part 2 — Implementation Plan

## Overview

Builds on plans/nl-workflow-compiler/ (Part 1). Adds a per-page live loop compiler (`--live`), smart ARIA filtering to reduce token cost, an enhanced self-healer with full workflow context, and auto-save of live-run steps as deterministic JSON. All changes are Engine-layer only — no POM, Glue, or exam changes.

## Prerequisites
- plans/nl-workflow-compiler/ Conversations 1–2 DONE
- `stepper/engine/compiler/` module exists (NLCompiler, PromptBuilder, OutputParser, site_registry.py)
- `stepper/engine/ai/service.py` has `"compile"` task type
- `--compile` flag works in main.py

## Layer Architecture

```
CLI: python stepper/main.py --live "intent" --site saucedemo
        │
        ▼
live_workflow(args)  [main.py]
        │
        ▼
LiveLoopCompiler  [engine/compiler/live_loop.py]
        │
        ├── page.on("framenavigated") → navigation detection
        │
        ├── Per-page iteration:
        │     ARIAFilter.apply(tree, strategy)  [engine/compiler/aria_filter.py]
        │           ↓
        │     PromptBuilder.build(intent, filtered_tree, schema, completed_so_far)
        │           ↓
        │     AIService.chat(task_type="compile")
        │           ↓
        │     OutputParser.parse() → page_steps
        │           ↓
        │     StepRunner.run(page_steps)  [existing, unchanged]
        │           ↓
        │     [navigation detected] → next iteration
        │
        └── save all_steps → live_<timestamp>.json

Enhanced AiHealer  [engine/healer/ai_healer.py]
        │  heal(step, error, dom,
        │        all_steps=None, current_index=None,
        │        completed_steps=None, context_vars=None,
        │        aria_snapshot=None)
        └── nearby_steps (±3) injected into prompt when provided
```

---

## Phases

### Phase 1: ARIAFilter module
**Layer:** Engine
**Files:**
- `stepper/engine/compiler/aria_filter.py` — NEW: `ARIAFilter` class

**Details:**
```python
class ARIAFilter:
    INTERACTIVE_ROLES = {
        "button", "textbox", "link", "combobox",
        "checkbox", "radio", "menuitem", "tab", "option",
        "searchbox", "spinbutton", "slider"
    }

    @classmethod
    def select_strategy(cls, node_count: int) -> str:
        """≤50 → full, 51–150 → interactive_only, 151+ → viewport_interactive"""

    @classmethod
    def count_nodes(cls, tree: dict | list) -> int:
        """Recursively count all nodes in ARIA tree."""

    @classmethod
    def apply(cls, tree: dict | list, strategy: str, page=None) -> list[dict]:
        """
        Returns flat list of relevant ARIA node dicts.
        strategy: "full" | "interactive_only" | "viewport_interactive"
        page: Playwright Page, required for viewport_interactive (bounding box)
        Falls back to interactive_only if viewport check fails.
        Falls back to full if result is empty after filtering.
        """

    @classmethod
    def to_compact_json(cls, nodes: list[dict]) -> str:
        """Serialize node list to compact JSON string for prompt injection."""
```

`interactive_only`: walk tree recursively, keep nodes whose `role` is in `INTERACTIVE_ROLES`. Include `name`, `label`, `placeholder`, `value` fields if present.

`viewport_interactive`: same as interactive_only, then filter by `page.evaluate()` bounding box check — keep nodes whose element is within viewport bounds. Falls back to interactive_only if evaluate fails.

**Verify:** `python -c "from engine.compiler.aria_filter import ARIAFilter; print('ok')"`

---

### Phase 2: LiveLoopCompiler
**Layer:** Engine
**Files:**
- `stepper/engine/compiler/live_loop.py` — NEW: `LiveLoopCompiler` class

**Details:**
```python
class LiveLoopCompiler:
    MAX_PAGE_CYCLES = 10
    MAX_STEPS_PER_PAGE = 15
    STALL_THRESHOLD = 3  # same URL repeated N times → stop

    def __init__(self, action_registry, ai_service=None):
        ...

    async def run(
        self,
        intent: str,
        base_url: str,
        output_path: Path,
        headless: bool = True,
        resolver=None,
    ) -> Path:
        """
        Main entry point. Opens browser, runs per-page loop, saves JSON.
        Returns path to saved workflow JSON.
        """
```

**Per-page loop logic:**
1. Navigate to base_url
2. Register `page.on("framenavigated", _on_nav)` — sets `_navigated = True`
3. Snapshot ARIA → `ARIAFilter.select_strategy(node_count)` → `ARIAFilter.apply()`
4. Build prompt with: intent + filtered ARIA + action schema + `completed_steps_summary`
5. Call `AIService.chat(task_type="compile")` → `OutputParser.parse()`
6. If empty steps → break (done)
7. Reset `_navigated = False`
8. `StepRunner.run(page_steps)` — use existing runner
9. Wait up to 2s for `_navigated` → if True: new page, continue loop
10. If same URL after execution: stall_count += 1; if stall_count >= STALL_THRESHOLD: break
11. Collect all steps; save to output_path

`completed_steps_summary`: compact list of already-executed action names (not full step dicts) — gives AI context without huge token cost.

**Verify:** `python -c "from engine.compiler.live_loop import LiveLoopCompiler; print('ok')"`

---

### Phase 3: Enhanced AiHealer — nearby steps + context vars only
**Layer:** Engine
**Files:**
- `stepper/engine/healer/ai_healer.py` — modify `heal()` + `_SYSTEM_TEMPLATE`
- `stepper/engine/healer/interfaces.py` — update `HealerStrategy.heal()` signature

**Rationale:**
`DOMSnapshotCascade` already sends DOM/ARIA context via `dom.content`. The only missing
signal is *where in the flow* the failure occurred. Nearby steps (±3) + context_vars give
the AI enough to infer page/phase (~150 extra tokens). Full step list and aria_snapshot
are excluded — redundant with dom.content or too noisy.

**Details:**

Add optional keyword-only params to `HealerStrategy.heal()` (ABC):
```python
async def heal(
    self,
    step: StepConfig,
    error: str,
    dom: DomPayload,
    *,                            # keyword-only — no breaking change
    all_steps: list | None = None,
    current_index: int | None = None,
    context_vars: dict | None = None,
) -> list[StepConfig]:
```

In `AiHealer.heal()`:
- When `all_steps` and `current_index` are both provided:
  - `nearby_steps = all_steps[max(0, current_index-3) : current_index+4]`
  - Serialize as compact dicts: `{"action": s.action, "description": s.description}` only
  - Add to `user_msg` JSON:
    ```json
    "workflow_context": {
      "current_index": 6,
      "total_steps": 9,
      "nearby_steps": [...],
      "context_vars": {"username": "standard_user"}
    }
    ```
- Do NOT include aria_snapshot — DOMSnapshotCascade covers this already
- Update `_SYSTEM_TEMPLATE` rule 7:
  `"7. If workflow_context is provided, use nearby_steps to infer which page/phase the automation is in — this narrows which element to target."`
- Keep fast path (healed_cfg is not None) unchanged — short-circuits before this logic
- Log: `"[AiHealer] heal with workflow context (step {current_index}/{total})"` or `"[AiHealer] heal (no context)"`

**Verify:**
```python
python -c "
import inspect
from engine.healer.ai_healer import AiHealer
sig = inspect.signature(AiHealer.heal)
assert 'all_steps' in sig.parameters
assert 'context_vars' in sig.parameters
assert 'aria_snapshot' not in sig.parameters, 'aria_snapshot should NOT be here'
print('ok')
"
```

---

### Phase 4: CLI --live flag + auto-save
**Layer:** Engine / CLI
**Files:**
- `stepper/main.py` — add `--live` flag + `live_workflow()` async function

**Details:**

New arg: `--live TEXT` (mutually exclusive with `--compile`, `--workflow`, `--task`)

`live_workflow(args)`:
1. `build_default_registry()` + `register_all_sites()`
2. `base_url = SITE_CONFIGS[args.site]["base_url"]`
3. Default output: `stepper/sites/<site>/workflows/live_<YYYYMMDD_HHMMSS>.json`
4. `resolver = build_resolver(s.use_visual_ai)`
5. `compiler = LiveLoopCompiler(action_registry, ai_service=AIService())`
6. `output = await compiler.run(intent, base_url, output_path, headless=not args.show, resolver=resolver)`
7. Print:
   ```
   Workflow saved to: <path>
   Run deterministically: python stepper/main.py --workflow <path>
   ```

Also wire full context into the healer call in `StepRunner` — pass `all_steps`, `current_index`, `completed_steps` when `--heal N > 0`.

**Verify:**
```bash
python stepper/main.py --live "log in as standard_user, add Sauce Labs Backpack to cart, go to cart, checkout with name Test User zip 12345" --site saucedemo --show
# Should navigate page by page, print step counts per page, save live_*.json
python stepper/main.py --workflow stepper/sites/saucedemo/workflows/live_*.json --show --heal 1
```

---

## Key Decisions
- `LiveLoopCompiler` owns its own browser — does not share with `StepRunner` to keep lifecycles clean
- ARIA filter strategy logged at DEBUG per page cycle so token audit is easy
- Healer context is keyword-only to avoid breaking callers that pass positional args
- Auto-save happens even on partial completion (with `_partial` suffix) so debugging is possible
