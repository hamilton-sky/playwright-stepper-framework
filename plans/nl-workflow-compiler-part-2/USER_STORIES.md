# NL Workflow Compiler Part 2 — User Stories

## Context

Part 1 (plans/nl-workflow-compiler/) delivered compile-once: one ARIA snapshot at the site's base URL, one AI call, one saved JSON. This works well for simple single-page flows but struggles with multi-page journeys where intermediate pages have elements the single snapshot never saw.

Part 2 upgrades to a **live loop**: the AI plans and executes page by page, snapping the real ARIA tree at each navigation boundary. The result is auto-saved as deterministic JSON, so every subsequent run is free of AI calls. It also upgrades the self-healer with full workflow context so recovery is smarter.

---

## Stories

### Story 2.1: Per-page live loop via --live flag
**As a** QA engineer, **I want** to run `python stepper/main.py --live "log in, sort products, add to cart, checkout" --site saucedemo`, **so that** the AI sees the real DOM at each page and produces accurate steps for every stage of the flow.

**Acceptance Criteria:**
- [ ] `--live` flag accepted by main.py alongside `--site` and `--output`
- [ ] Browser opens, navigates to site base URL
- [ ] AI plans steps for the current page from its ARIA snapshot
- [ ] Steps execute; navigation is detected via URL change
- [ ] On new page: new ARIA snapshot → AI plans next steps → execute
- [ ] Loop ends when AI returns empty steps or intent is marked complete
- [ ] All executed steps collected and auto-saved as standard workflow JSON
- [ ] Saved JSON runs deterministically with `python stepper/main.py --workflow <path>`

**Edge Cases:**
- Loop runs more than 10 page cycles → stop with warning (safety cap)
- Navigation not detected after 5s → treat as same-page continuation

### Story 2.2: ARIA filtering strategies
**As a** framework author, **I want** the compiler to send only the relevant portion of the ARIA tree to the AI, **so that** token cost stays low even on complex pages.

**Acceptance Criteria:**
- [ ] `ARIAFilter` class with three strategies: `interactive_only`, `viewport_interactive`, `full`
- [ ] Strategy selected dynamically: ≤50 nodes → full; 51–150 → interactive_only; 151+ → viewport_interactive
- [ ] `interactive_only` returns only nodes with role in {button, textbox, link, combobox, checkbox, radio, menuitem, tab, option}
- [ ] `viewport_interactive` intersects interactive nodes with those visible in viewport (bounding box check)
- [ ] Filter result always includes node count and strategy name in log

**Edge Cases:**
- After filtering, 0 nodes remain → fall back to `full` with a warning
- Viewport bounding box unavailable → fall back to `interactive_only`

### Story 2.3: Enhanced self-healer with full workflow context
**As a** CI operator, **I want** the healer to know the full step list and current position when a locator fails, **so that** it makes smarter recovery decisions (e.g., understanding we're in checkout, not on the product page).

**Acceptance Criteria:**
- [ ] `AiHealer.heal()` optionally accepts: `all_steps`, `current_index`, `completed_steps`, `context_vars`, `aria_snapshot`
- [ ] When provided, these are included in the AI prompt as structured JSON
- [ ] System prompt updated: "You know the full workflow context — use it to infer the correct element"
- [ ] Existing callers that pass only `(step, error, dom)` still work (all new params optional)
- [ ] Log shows whether full context was included in the heal call

**Edge Cases:**
- Full context makes prompt exceed token limit → truncate `all_steps` to ±3 steps around current index

### Story 2.4: Auto-save after live run
**As a** developer, **I want** the live loop to save the resolved steps as a JSON file when it completes, **so that** I get compile-once determinism for free on the second run.

**Acceptance Criteria:**
- [ ] After live loop completes, all steps written to `stepper/sites/<site>/workflows/live_<timestamp>.json`
- [ ] Terminal prints: `Workflow saved to: <path>` + `Run deterministically: python stepper/main.py --workflow <path>`
- [ ] Saved JSON is valid and passes the existing `JsonFilePlanner` load
- [ ] `--output` flag overrides the auto-generated filename

**Edge Cases:**
- Live loop exits mid-flow (error) → save partial steps with `_partial` suffix, warn user
