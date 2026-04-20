# Self-Healing Planner — User Stories

## Context
When `StepRunner` executes a step that was generated (or manually authored) and the
`GlueAction` fails — because a selector changed, a page loaded differently, or the
LLM transpiler produced a slightly wrong step — the framework currently hard-stops.
The only recovery is manual: edit the workflow or cfg list, re-run.

The self-healing feature adds an AI-powered recovery loop: when a step fails after
all its configured retries, the runner takes a DOM snapshot, passes the original step
+ error + snapshot to a `HealerStrategy`, receives a replacement `[StepConfig]`, and
executes those instead. If healing also fails, the original error surfaces unchanged.
This applies to any site and any action type — it's a pure engine-layer capability.

## Stories

### Story 1.1: Automatic Step Replacement on Failure
**As a** test author, **I want** a failed step to be automatically re-planned using
the current DOM context, **so that** transient selector mismatches don't require
manual workflow edits.

**Acceptance Criteria:**
- [ ] `HealerStrategy` interface defined in engine layer
- [ ] When a step fails and `max_heal_attempts > 0`, `StepRunner` calls
  `HealerStrategy.heal(step, error, dom_snapshot)` before hard-stopping
- [ ] The healer returns a replacement `[StepConfig]`; runner executes them
- [ ] If healing succeeds, the original step result is marked `healed` (not `failed`)
- [ ] If all healing attempts also fail, the original error is surfaced

**Edge Cases:**
- Healer itself raises an exception — treated as a healing failure, doesn't propagate
- Replacement steps contain an unknown action — caught by `ActionRegistry.create()`

---

### Story 1.2: DOM Snapshot for Healing Context
**As a** healer implementation, **I want** a clean, size-bounded DOM snapshot of the
current page, **so that** the LLM can reason about which elements are actually present.

**Acceptance Criteria:**
- [ ] `DOMSnapshot.capture(page) → str` returns a simplified HTML string
- [ ] Snapshot is capped at a configurable max character count (default 8000)
- [ ] Snapshot strips `<script>`, `<style>`, `<svg>` tags to reduce noise
- [ ] `DOMSnapshot.capture()` never raises — returns empty string on failure

**Edge Cases:**
- Page is mid-navigation when snapshot is taken — returns whatever is available
- Page content is enormous — truncated to cap, not crashed

---

### Story 1.3: Claude-Powered Healer
**As a** test author, **I want** the default healer to use Claude to suggest replacement
steps, **so that** healing leverages the same LLM grounding as the transpiler.

**Acceptance Criteria:**
- [ ] `ClaudeHealer` implements `HealerStrategy`
- [ ] `ClaudeHealer.heal(step, error, dom_snapshot)` calls Claude with: original step
  JSON, error message, DOM snapshot, and the registered action schema
- [ ] Claude returns a JSON array of replacement steps
- [ ] Replacement steps are validated by `PlanValidator` before being returned
- [ ] If Claude's response is invalid, `ClaudeHealer` raises `HealingError`

**Edge Cases:**
- Claude API unavailable — raises `HealingError`, runner surfaces original error
- Claude returns the exact same step — allowed; runner retries it (may re-fail)

---

### Story 1.4: Configurable Healing in Workflow
**As a** test author, **I want** to control healing behaviour per-workflow via the
`settings` block, **so that** I can disable healing for deterministic tests.

**Acceptance Criteria:**
- [ ] `settings.max_heal_attempts` (int, default 0 = disabled) read from workflow JSON
- [ ] `settings.max_heal_attempts` also settable via `--heal N` CLI flag in `main.py`
- [ ] When `max_heal_attempts = 0`, healing loop is completely bypassed (no API calls)
- [ ] Each step can override with `"heal": false` to opt out of healing

**Edge Cases:**
- `max_heal_attempts` set to a very large number — clamped to 3 max
- Healing succeeds on attempt 2 of 3 — remaining attempts not consumed
