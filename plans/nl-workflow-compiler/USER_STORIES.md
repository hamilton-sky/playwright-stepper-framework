# NL Workflow Compiler — User Stories

## Context

Today, authoring a workflow requires writing explicit JSON with action names, params, and cfg selector lists — knowledge that takes time to acquire. This feature adds a **compile** mode: the user writes a plain-language description of what the automation should do, the system opens the target site in a browser, snapshots the ARIA accessibility tree, and asks an AI (Groq first, Claude fallback) to produce a fully-specified workflow JSON. The result is saved to disk and runs deterministically with the existing runner + resolver cascade + self-healing — no AI tokens at execution time.

---

## Stories

### Story 1.1: Compile a workflow from natural language
**As a** QA engineer, **I want** to run `python stepper/main.py --compile "log in, add a product, checkout" --site saucedemo`, **so that** I get a ready-to-run workflow JSON without writing any selectors or action names manually.

**Acceptance Criteria:**
- [ ] `--compile` flag accepted by main.py alongside `--site` and `--output`
- [ ] Browser opens, navigates to site base URL, takes ARIA snapshot
- [ ] AI receives: action registry list + cfg key guide + ARIA tree + user intent
- [ ] AI response parsed into valid workflow JSON with cfg lists populated
- [ ] JSON saved to `stepper/sites/<site>/workflows/<generated-name>.json`
- [ ] Saved JSON runs successfully with `python stepper/main.py --workflow <path>`

**Edge Cases:**
- AI returns malformed JSON → retry once, then raise with clear message
- ARIA snapshot is empty (page load failed) → raise before calling AI

### Story 1.2: Groq as primary, Claude as fallback
**As a** developer, **I want** the compile call to use Groq first, **so that** token cost is minimal during workflow authoring.

**Acceptance Criteria:**
- [ ] Compile task type added to AIService chain: `["groq", "gemini", "claude"]`
- [ ] Falls back automatically when Groq key is absent or rate-limited
- [ ] Log shows which provider answered

**Edge Cases:**
- All providers fail → clear error message listing which keys are missing

### Story 1.3: ARIA snapshot drives cfg list generation
**As a** framework author, **I want** the AI to use the live ARIA tree to populate cfg lists, **so that** generated selectors match the real DOM instead of hallucinated ones.

**Acceptance Criteria:**
- [ ] Compiler calls `page.accessibility.snapshot()` after page load
- [ ] Snapshot serialised to compact JSON and injected into the AI prompt
- [ ] AI prompt instructs model to prefer `role`+`name` over `css`/`xpath` (cascade priority)
- [ ] Generated cfg lists use correct key names (`role`, `label`, `placeholder`, `css`, `id`, `xpath`)

**Edge Cases:**
- Page has very large ARIA tree → truncate to first 200 nodes with a warning

### Story 1.4: Output is deterministic and self-healing compatible
**As a** CI operator, **I want** the compiled JSON to be a standard workflow file, **so that** every subsequent run is deterministic and self-healing can fix stale locators automatically.

**Acceptance Criteria:**
- [ ] Compiled JSON is identical in schema to hand-authored workflow JSON
- [ ] Running with `--heal N` works transparently on compiled workflows
- [ ] No AI calls at execution time unless a locator breaks and healing triggers
