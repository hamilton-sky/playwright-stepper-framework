# Self-Healing Planner — Implementation Plan

## Overview
Add an AI-powered recovery loop to `StepRunner`: when a step fails after all retries,
the runner runs the `DOMSnapshotCascade` (embed-first, min-token strategy), calls
`AiHealer` to produce replacement steps, and executes those instead.
`AiHealer` uses the same Groq→Gemini→Claude provider cascade as `AIPickResolver`.
This is a pure engine-layer change — POM and glue layers are not touched.

## Layer Architecture

```
StepRunner.run()  ← engine/runner/step_runner.py  (MODIFIED)
     │  step fails after all retries
     ▼
DOMSnapshotCascade.capture(page, step)   ← engine/healer/dom_snapshot.py  (NEW)
     │  embed-first cascade — passes minimum tokens to AI:
     │  1. MiniLM embed: step title vs interactive elements
     │     score ≥ 0.85 + unique → heal with ZERO AI call
     │     score ≥ 0.85 + ambiguous → top-N candidates (~20–40 tok)
     │     0.50–0.85 → best match + scoped DOM area (~40–150 tok)
     │     < 0.50 → full aria snapshot (~200–500 tok)
     ▼
HealerStrategy.heal(          ← engine/healer/interfaces.py     (NEW)
    step, error, dom_payload)
     │  returns [StepConfig] replacement steps
     ▼
AiHealer                      ← engine/healer/ai_healer.py      (NEW)
     │  Groq/Qwen (rotation keys, free) → Gemini Flash → Claude Haiku
     │  validates replacement steps via PlanValidator
     ▼
StepRunner executes replacement steps
     │  success → mark original step "healed"
     │  failure → surface original error
```

No POM or glue files touched. No workflow JSON changes required (healing is
transparent — the same workflow JSON runs with or without healing enabled).

---

## Phases

### Phase 0.5: AIService — centralised LLM provider layer
**Layer:** Engine (`stepper/engine/ai/`)
**Files:**
- `stepper/engine/ai/__init__.py` — NEW: empty package init
- `stepper/engine/ai/providers.py` — NEW: `GroqProvider`, `GeminiProvider`, `ClaudeProvider` (~20 lines each)
- `stepper/engine/ai/service.py` — NEW: `AIService`

**Why now:** Three places in the engine call LLMs (`ai_pick_resolver.py`, `planner.py`, and the upcoming `ai_healer.py`). Centralising them means adding a new provider = one new class, zero changes to callers.

**Groq rotation:** `GROQ_API_KEY=key1,key2,key3` — same round-robin pattern as `AIPickResolver`. Each key = 14,400 req/day free.

**Details:**

```python
# providers.py
class GroqProvider:
    # Reads GROQ_API_KEY, splits on comma, round-robin rotation
    async def chat(self, prompt: str) -> str: ...

class GeminiProvider:
    # Reads GEMINI_API_KEY
    async def chat(self, prompt: str) -> str: ...

class ClaudeProvider:
    # Reads ANTHROPIC_API_KEY
    async def chat(self, prompt: str, model: str) -> str: ...

# service.py
class AIService:
    TASK_CHAINS = {
        "classify": [GroqProvider, GeminiProvider, ClaudeProvider],  # cheapest first
        "plan":     [ClaudeProvider],
        "heal":     [GroqProvider, GeminiProvider, ClaudeProvider],  # cheapest first
    }

    async def chat(self, prompt: str, task_type: str = "classify") -> str:
        """Try each provider in chain; return first success."""
```

**Callers after this phase:**
- `AIPickResolver` → `AIService.chat(prompt, task_type="classify")`
- `ClaudePlanner` → `AIService.chat(prompt, task_type="plan")`
- `AiHealer` (Phase 2) → `AIService.chat(prompt, task_type="heal")`

**Verify:**
```bash
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.ai.service import AIService
from engine.ai.providers import ClaudeProvider, GroqProvider, GeminiProvider
print('AIService:', AIService)
print('ok')
"
```

---

### Phase 1: HealerStrategy interface + DOMSnapshotCascade utility
**Layer:** Engine (`stepper/engine/healer/`)
**Files:**
- `stepper/engine/healer/__init__.py` — NEW: empty package init
- `stepper/engine/healer/interfaces.py` — NEW: `HealerStrategy` ABC, `HealingError`, `DomPayload`
- `stepper/engine/healer/dom_snapshot.py` — NEW: `DOMSnapshotCascade` class

**Details:**

`HealerStrategy` (ABC):
```python
class HealerStrategy(ABC):
    @abstractmethod
    async def heal(
        self,
        step: StepConfig,
        error: str,
        dom_payload: DomPayload,
    ) -> list[StepConfig]:
        """Return replacement steps. Raise HealingError if healing not possible."""
```

`DomPayload` — dataclass carrying the cascade result:
```python
@dataclass
class DomPayload:
    strategy_used: str          # "embed_direct" | "embed_candidates" | "scoped" | "aria"
    content: str                # JSON or aria snapshot — sent to AI
    healed_cfg: dict | None     # set only when Strategy 1 resolves without AI
    token_estimate: int
```

`HealingError(Exception)` — raised when healer cannot produce a valid replacement.

`DOMSnapshotCascade` — embed-first cascade with threshold decision tree:

**Composite embed query** — the query vector is richer than just the step title:
```python
def _build_query(step: StepConfig) -> str:
    parts = [step.description or ""]
    # append extra values — often carry the most specific signal
    for v in (step.extra or {}).values():
        if isinstance(v, str):
            parts.append(v)
    query = " ".join(p for p in parts if p).strip()
    # fallback: parse action name if description is missing or too short
    if len(query) < 15:
        query = step.action.replace("_", " ").split()[-3:]  # "ol_add_to_shelf" → "add to shelf"
        query = " ".join(query) + " " + " ".join(str(v) for v in (step.extra or {}).values())
    return query
```
Examples:
- `description="Add book to reading list"` + `extra={book_title:"The Hobbit"}` → `"Add book to reading list The Hobbit"`
- `description="step 3"` + `action="ol_add_to_shelf"` → `"add to shelf"`

```
  Embed _build_query(step) → vector T  (MiniLM-L6-v2, already loaded by resolver)
  Embed each element's {text, aria-label, placeholder, name} → vectors E[]
  score[i] = cosine_similarity(T, E[i])

  ┌──────────────────────────────────────────────────────────────────┐
  │                  THRESHOLD DECISION TREE                         │
  │                                                                  │
  │  score ≥ 0.85  AND  exactly 1 match                             │
  │  → healed_cfg generated from element attributes                  │
  │  → NO AI CALL  (DomPayload.healed_cfg is set)        ~0 tokens  │
  │                                                                  │
  │  score ≥ 0.85  AND  2+ matches  (ambiguous high)               │
  │  → top-N candidates JSON sent to AiHealer            ~20–40 tok │
  │                                                                  │
  │  0.50 ≤ score < 0.85  AND  unique best                         │
  │  → best match + scoped DOM area (ancestor region)    ~40–80 tok │
  │                                                                  │
  │  0.50 ≤ score < 0.85  AND  2+ matches                          │
  │  → top-N + scoped DOM area                          ~80–150 tok │
  │                                                                  │
  │  score < 0.50  (all candidates weak)                            │
  │  → full page.accessibility.snapshot()              ~200–500 tok │
  └──────────────────────────────────────────────────────────────────┘
```

`async DOMSnapshotCascade.capture(page, step) -> DomPayload`

**Interactive element extraction (all strategies use this as input):**
```python
elements = await page.evaluate("""() =>
  [...document.querySelectorAll(
    'button,a,input,select,textarea,[role],[aria-label]'
  )].map(el => ({
    tag: el.tagName, text: el.textContent?.trim().slice(0,80),
    role: el.getAttribute('role'),
    aria: el.getAttribute('aria-label'),
    id: el.id, placeholder: el.getAttribute('placeholder')
  }))
""")
```

**Scoped area (used when 0.50 ≤ score < 0.85):**
```python
# Walk up from the best-match element to the nearest structural boundary
container_html = await page.evaluate(
    "(sel) => document.querySelector(sel)"
    "?.closest('form,main,section,nav,dialog')?.outerHTML",
    best_match_selector
)
```

**Full aria snapshot (used when score < 0.50):**
```python
snapshot = await page.accessibility.snapshot()
```

**Verify:**
```bash
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.healer.interfaces import HealerStrategy, HealingError, DomPayload
from engine.healer.dom_snapshot import DOMSnapshotCascade
print('HealerStrategy:', HealerStrategy)
print('DOMSnapshotCascade:', DOMSnapshotCascade)
print('ok')
"
```

---

### Phase 2: AiHealer implementation
**Layer:** Engine (`stepper/engine/healer/`)
**Files:**
- `stepper/engine/healer/ai_healer.py` — NEW: `AiHealer(HealerStrategy)`

**Details:**

`AiHealer.__init__(action_schema: dict, ai_service: AIService)`:
- `action_schema` — same format as `ActionSchemaExtractor.extract()` output
- Provider cascade via `AIService` (task_type="heal"): Groq → Gemini → Claude Haiku

`AiHealer.heal(step, error, dom_payload) -> list[StepConfig]`:
1. If `dom_payload.healed_cfg is not None` → embed resolved it, build `StepConfig` directly — **no AI call**
2. Otherwise build system prompt: "You are a browser automation healer. Given a failed
   step, its error, and the current page context, return a JSON array of replacement
   steps using ONLY these registered actions: {action_block}"
3. Build user message: JSON of original step + error string + `dom_payload.content`
4. Call `ai_service.chat(prompt, task_type="heal")`; strip markdown fences
5. Parse JSON → `[dict_to_step_config(s) for s in raw]`
6. If result is a single dict, wrap in list
7. Validate each replacement step's action is in `action_schema` keys
8. Raise `HealingError` if response is empty array or invalid JSON

Import `dict_to_step_config` from `engine.utils` (same as `ClaudePlanner`).
Import `ActionSchemaExtractor.to_prompt_block` from `engine.planner.schema_extractor`.

**Verify:**
```bash
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.healer.ai_healer import AiHealer
from engine.healer.interfaces import HealingError
print('AiHealer:', AiHealer)
print('ok')
"
```

---

### Phase 3: Wire healing loop into StepRunner (includes heal_assert)
**Layer:** Engine (`stepper/engine/runner/step_runner.py`)
**Files:**
- `stepper/engine/runner/step_runner.py` — MODIFY: add healing loop + post-heal assertion

**Details:**

Add `healer: HealerStrategy | None = None` and `max_heal_attempts: int = 0`
params to `StepRunner.__init__`.

In `StepRunner.run()`, after the retry loop produces a `failed` result:

```python
heal_attempt = 0
while (result.status == "failed"
       and self._healer is not None
       and getattr(step, 'heal', True) is not False
       and heal_attempt < min(self._max_heal_attempts, 3)):
    heal_attempt += 1
    self._notify_log(
        f"⚕ Healing step {idx+1} (attempt {heal_attempt})", "warning"
    )
    try:
        dom_payload = await DOMSnapshotCascade.capture(self._page, step)
        replacement_steps = await self._healer.heal(step, result.error, dom_payload)
        replacement_results, ctx = await self.run(replacement_steps, ctx)

        if all(r.status != "failed" for r in replacement_results):
            # Post-heal assertion — proves semantic correctness, not just "ran"
            if step.heal_assert and not await _run_heal_assert(self._page, step.heal_assert):
                self._notify_log(
                    f"⚕ Heal attempt {heal_attempt} passed but assertion failed "
                    f"— wrong element clicked, retrying", "warning"
                )
                continue   # next heal attempt with same or wider context
            result = dataclasses.replace(result, status="healed", error=None)
            break
    except Exception as heal_exc:
        logger.warning(f"Healing attempt {heal_attempt} failed: {heal_exc}")
```

**`_run_heal_assert(page, heal_assert: dict) -> bool`** — private helper, ~15 lines:

```python
async def _run_heal_assert(page, spec: dict) -> bool:
    try:
        if "url_contains" in spec:
            if spec["url_contains"] not in page.url:
                return False
        if "url_not_contains" in spec:
            if spec["url_not_contains"] in page.url:
                return False
        if "element_visible" in spec:
            if not await page.locator(spec["element_visible"]).is_visible():
                return False
        if "element_text_contains" in spec:
            sel, text = spec["element_text_contains"]["selector"], spec["element_text_contains"]["text"]
            if text not in await page.locator(sel).inner_text():
                return False
        return True
    except Exception:
        return False   # assertion error → treat as failed
```

**Supported assert keys** (all optional, all checked if present):

| Key | Type | Example |
|---|---|---|
| `url_contains` | str | `"/account"` |
| `url_not_contains` | str | `"/error"` |
| `element_visible` | CSS selector | `".reading-list-count"` |
| `element_text_contains` | `{selector, text}` | `{".flash", "added"}` |

**Workflow JSON usage:**
```json
{
  "action": "ol_add_to_shelf",
  "description": "Add book to reading list",
  "heal_assert": {
    "element_visible": ".reading-list-count",
    "element_text_contains": {"selector": ".flash-message", "text": "added"}
  }
}
```
`heal_assert` is optional — if absent, healing falls back to "ran without error" check only.
Steps with `"heal": false` skip the healing loop entirely; `heal_assert` is never evaluated.

Mark a healed result with `status="healed"` — add `"healed"` to the valid status
literals in `engine/interfaces.py` (`StepResult`).

**Verify:**
```bash
python stepper/main.py \
  --workflow stepper/sites/openlibrary/workflows/search_and_add.json \
  --show
# All existing tests pass; healing not triggered on normal runs
pytest exam/
```

---

### Phase 4: CLI flag + workflow settings integration
**Layer:** Entry point (`stepper/main.py`)
**Files:**
- `stepper/main.py` — MODIFY: add `--heal N` arg, pass healer to `StepRunner`
- `stepper/engine/interfaces.py` — MODIFY: add `heal: bool = True` and `heal_assert: dict | None = None` to `StepConfig`

**Details:**

In `main()`:
```python
parser.add_argument("--heal", type=int, default=0, metavar="N",
                    help="Max self-healing attempts per step (default 0 = disabled)")
```

In `run()`:
- Read `max_heal_attempts` from `args.heal` (CLI) and `settings.max_heal_attempts`
  (workflow JSON `settings` block); CLI takes precedence
- If `max_heal_attempts > 0` and `ANTHROPIC_API_KEY` is set:
  - Build `schema = ActionSchemaExtractor.extract(action_registry)`
  - Construct `healer = AiHealer(action_schema=schema)`
  - Pass `healer=healer, max_heal_attempts=max_heal_attempts` to `StepRunner`
- If `max_heal_attempts == 0` or no API key: pass `healer=None` (no behaviour change)

Add `heal: bool = True` field to `StepConfig` dataclass so steps can opt out
with `"heal": false` in workflow JSON.

**Verify:**
```bash
python stepper/main.py \
  --workflow stepper/sites/openlibrary/workflows/search_and_add.json \
  --heal 2 --show
# Healing enabled; normal steps pass; no unnecessary API calls
pytest exam/
```

---

### Phase 5: Healing cache + selector writeback
**Layer:** Engine (`stepper/engine/healer/`)
**Files:**
- `stepper/engine/healer/healing_cache.py` — NEW: `HealingCache`
- `stepper/sites/<site>/healing_overrides.json` — auto-created on first heal

**Why:** When a heal succeeds the new selector is known. Throwing it away means the
next run pays the same embed+AI cost again. Instead, persist the healed cfg and inject
it at priority 0 (tried first) on subsequent runs — effectively self-updating the
element resolution without touching POM source files.

**How it works:**

```
  Heal succeeds (status="healed") with new cfg, e.g.:
  {"role": "button", "name": "Want to Read", "priority": 0}
                │
                ▼
  HealingCache.record(site, action_name, param_fingerprint, healed_cfg)
                │
                ▼
  Writes to stepper/sites/<site>/healing_overrides.json:
  {
    "ol_add_to_shelf": {
      "abc123": {                      ← fingerprint of step params
        "healed_cfg": {"role": "button", "name": "Want to Read"},
        "healed_at": "2026-04-20T14:32:00",
        "original_error": "ElementNotFoundError: SUBMIT_CFG"
      }
    }
  }
```

**Cache key** — `action_name:param_fingerprint` where fingerprint is a stable hash
of the step params. Defaults to `"default"` when params are empty or non-discriminating
(i.e. when the action always targets the same element regardless of params):

```python
import hashlib, json

def _param_fingerprint(step: StepConfig) -> str:
    params = step.params or {}
    if not params:
        return "default"
    return hashlib.md5(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()[:8]

cache_key = f"{step.action}:{_param_fingerprint(step)}"
# e.g. "ol_add_to_shelf:default"        ← same button every time
# e.g. "sd_add_to_cart:a3f8c120"        ← different product, different button
```

Examples:
- `ol_add_to_shelf` — always targets the same "Add to shelf" button regardless of
  which book → fingerprint `"default"`, one cache entry covers all books
- `sd_add_to_cart` with `params={"product": "Sauce Labs Backpack"}` → fingerprint
  `"a3f8c120"`, separate entry per product since each has its own Add to Cart button

**Injection at startup** — `HealingCache.load(site)` returns a dict of
`action_name → {fingerprint → cfg}`. `StepRunner` checks the cache before
dispatching each step. If a match is found, it prepends `healed_cfg` at `priority=0`
to the step's resolution context so it's tried first — before any cfg list in the POM.

**Layer contract:** The POM source files are never modified. The overrides file is
a runtime config artifact, not code. Glue layer and POM layer stay unchanged.

**Reporter integration:** On heal, log a clear message:
```
⚕ Step healed: ol_add_to_shelf
   Old selector: {"role": "button", "name": "Add to Reading List"}
   New selector: {"role": "button", "name": "Want to Read"}
   Cached for next run → stepper/sites/openlibrary/healing_overrides.json
```
This gives developers the diff they need to update POM cfgs permanently if desired.

**Verify:**
```bash
# Run with a broken selector; healing fires and writes cache
python stepper/main.py --workflow ... --heal 2 --show
# Check cache file was written
cat stepper/sites/openlibrary/healing_overrides.json
# Run again — same step, no healing triggered (cache hit)
python stepper/main.py --workflow ... --heal 2 --show
# Reporter should show: "✓ ol_add_to_shelf (from healing cache)"
```

---

## Phase 0: Shared Planner Infrastructure
**Layer:** Engine (`stepper/engine/planner/`, `stepper/engine/`)
**Files:**
- `stepper/engine/planner/schema_extractor.py` — NEW: `ActionSchemaExtractor` class
- `stepper/engine/planner/__init__.py` — export `ActionSchemaExtractor`, `PlanValidator`
- `stepper/engine/planner/validator.py` — NEW: `PlanValidator`, `PlanValidationError`
- `stepper/engine/utils.py` — add `dict_to_step_config` if not already present

**Details:**

`ActionSchemaExtractor.extract(registry) → dict[str, dict]`:
- Reads `registry._registry` (dict of `action_name → ActionStrategy`)
- For each action captures: `description` (first line of class docstring or action_name),
  `params` (names from `_execute()` signature minus `self/page/step/resolver/context`)
- Returns schema dict keyed by action name

`ActionSchemaExtractor.to_prompt_block(schema) → str`:
- Formats schema as numbered list for Claude system prompt injection

`PlanValidationError(message: str, bad_steps: list)` — custom exception

`PlanValidator.validate(steps: list[StepConfig], registry: ActionRegistry) → None`:
- Checks every `step.action` is a key in `registry._registry`
- Checks every step has non-empty `action` and `description`
- Collects ALL errors before raising (no short-circuit)

`dict_to_step_config(d: dict) → StepConfig` (in `engine/utils.py`):
- Converts a raw dict to a `StepConfig` dataclass instance
- Only add if not already present

**Verify:**
```bash
python -c "
import sys; sys.path.insert(0, 'stepper')
from engine.planner.schema_extractor import ActionSchemaExtractor
from engine.planner.validator import PlanValidator, PlanValidationError
from engine.utils import dict_to_step_config
from engine.actions.factory import build_default_registry
r = build_default_registry()
schema = ActionSchemaExtractor.extract(r)
print('Schema keys:', list(schema.keys())[:3])
print('PlanValidator:', PlanValidator)
print('dict_to_step_config:', dict_to_step_config)
print('ok')
"
```

---

## Prerequisites
- `ANTHROPIC_API_KEY` set in environment (needed for ClaudeHealer, not for Phase 0–1)

## Key Decisions
- **Healing loop inside StepRunner** (not in ActionStrategy base) — StepRunner
  is the only place that knows a step has exhausted all its retries; ActionStrategy
  only handles single-attempt logic.
- **AiHealer uses Groq→Gemini→Claude cascade** — same pattern as `AIPickResolver`.
  Groq (free, rotation keys) handles most heals; Haiku is the last resort only.
- **Healing is opt-out per step** (`"heal": false`) not opt-in — most steps benefit;
  only assertions and count checks should be exempt.
- **Max 3 healing attempts hard-capped** — prevents infinite loops regardless of
  workflow `settings.max_heal_attempts` value.
- **Healing disabled by default** (`max_heal_attempts=0`) — zero behaviour change
  for existing workflows unless `--heal N` or `settings.max_heal_attempts` is set.
