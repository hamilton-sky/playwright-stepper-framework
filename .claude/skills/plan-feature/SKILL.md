---
name: plan-feature
description: Plan a new stepper framework feature by creating a plans folder with 8 files: USER_STORIES.md, IMPLEMENTATION_PLAN.md, PROGRESS.md, CONVERSATION_PROMPTS.md (max 4 conversations per folder), HAPPY_FLOW.md, EDGE_CASES.md, ARCHITECTURE_PROPOSAL.md, and FLOW_DIAGRAM.md.
argument-hint: "[feature-name, e.g., add-saucedemo-checkout, new-resolver-strategy, phptravels-flights]"
model: opus
---

Plan the **$ARGUMENTS** feature by creating a complete plans folder.

## Step 1: Understand the feature

Interview the user about the feature. Ask about:

- **What**: What does this feature do? What problem does it solve?
- **Layer scope**: POM only? Glue + POM? New site (all three layers)? Engine change?
- **Site**: Which site does it apply to (openlibrary / saucedemo / phptravels / new)?
- **Dependencies**: Does it depend on other features or unreleased actions?
- **Complexity estimate**: Small (1-2 conversations), Medium (3-4), Large (5+)?

If the user already provided a detailed description, skip to Step 2.

## Step 2: Research the codebase

Before writing any plans, explore the codebase to understand:

1. **Three-layer contract**: Read `.claude/rules/three-layer-contract.md` — know what belongs in POM vs. Glue vs. Flow
2. **Existing patterns**: Find similar sites/actions and how they were implemented (e.g., `stepper/sites/saucedemo/` for a new site)
3. **Key files**: Identify which files need to be created or modified across all three layers
4. **Resolver rules**: Check `.claude/rules/resolver-cascade.md` for cfg list conventions
5. **Test patterns**: Check `exam/` for existing test conventions if tests are in scope

## Step 3: Create the plans folder

Create `plans/$ARGUMENTS/` with **8 files**:

> **Conversation cap rule**: Each folder may contain at most **4 conversations**. If the feature needs more, split it into two folders:
> - `plans/$ARGUMENTS-part-1/` — first 4 conversations (foundation)
> - `plans/$ARGUMENTS-part-2/` — remaining conversations (depends on part-1 being DONE)

---

### 3a. USER_STORIES.md

```markdown
# [Feature Name] — User Stories

## Context
[1-2 paragraph problem statement — which site, what automation gap this fills]

## Stories

### Story N.N: [Story Title]
**As a** [test author / QA engineer], **I want** [goal], **so that** [benefit].

**Acceptance Criteria:**
- [ ] [Criterion 1]
- [ ] [Criterion 2]
- [ ] [Criterion 3]

**Edge Cases:**
- [Edge case 1]
- [Edge case 2]
```

---

### 3b. IMPLEMENTATION_PLAN.md

```markdown
# [Feature Name] — Implementation Plan

## Overview
[What this feature adds — which site, which actions, which workflow, 2-3 sentences]

## Layer Architecture
[Show how the feature spans POM / Glue / Flow layers]

```
Flow (JSON)  →  Glue (stepper/sites/…)  →  POM (poms/…)
   ↓                    ↓                        ↓
[workflow]         [action classes]         [locators + interactions]
```

## Phases

### Phase 1: [Phase Title] (estimated effort)
**Layer:** POM / Glue / Flow / Engine
**Files:**
- `poms/<site>/pages/<file>.py` — [what changes]
- `stepper/sites/<site>/pages/<file>.py` — NEW: [what it does]

**Details:**
[Specific implementation instructions — cfg list keys, method signatures, action names]

**Verify:** `pytest exam/` or `python stepper/main.py --workflow stepper/sites/<site>/workflows/<file>.json --show`

### Phase 2: [Phase Title] (estimated effort)
...

## Prerequisites
- [What must be true before starting]

## Key Decisions
- [Architecture decision 1 and rationale — e.g., which resolver keys to use]
- [Architecture decision 2 and rationale]
```

---

### 3c. PROGRESS.md

```markdown
# [Feature Name] — Progress

## Status: NOT STARTED

## Conversation Breakdown

| Conv | Phases | Scope | Status | Verify |
|------|--------|-------|--------|--------|
| 1 | [phases] | [scope summary] | TODO | `[verify command]` |
| 2 | [phases] | [scope summary] | TODO | `[verify command]` |
...

See **CONVERSATION_PROMPTS.md** for exact prompts to paste in each conversation.

## Phase Detail

| # | Phase | Layer | Description | Conv | Status | Key Files |
|---|-------|-------|-------------|------|--------|-----------|
| 1 | [name] | POM/Glue/Flow | [description] | 1 | TODO | `[files]` |
...

## Prerequisites
- [prerequisite 1]

## Blocked By
- Nothing / [blocker]
```

---

### 3d. CONVERSATION_PROMPTS.md (Conversation Script)

This is the key file — it contains **verbatim copy-paste prompts** for each conversation.
**Maximum 4 conversations per folder.** If more are needed, create a part-2 folder.

```markdown
# [Feature Name] — Conversation Guide

Split into N conversations (max 4). Each produces runnable, testable code.
After each conversation, **commit your changes** before starting the next.

---

## Conversation 1: [Title] (Phases X-Y)

**Prompt to paste:**
` ` `
Implement [Feature] Conversation 1 (Phases X-Y) from plans/$ARGUMENTS/IMPLEMENTATION_PLAN.md.

Scope:
- Phase X: [specific instructions with file paths and layer]
- Phase Y: [specific instructions with file paths and layer]

Three-layer rules to observe:
- All interactive locators must be cfg lists (see .claude/rules/pom-layer.md)
- Every POM construction must pass page=page, resolver=resolver (see .claude/rules/glue-layer.md)
- No raw page.locator() calls in glue files

Do NOT touch [exclusions — other layers, other sites, exam tests, etc.].
Verify: python stepper/main.py --workflow stepper/sites/<site>/workflows/<file>.json --show
After done, update plans/$ARGUMENTS/PROGRESS.md phases X-Y to DONE.

If verification fails and the fix requires out-of-scope changes, stop and report.
If fundamentally broken, rollback with git checkout on affected files and retry.
` ` `

**Expected output:** [what state the codebase should be in — which actions are registered and runnable]
**Files touched:** `[file list]`

---

## Conversation 2: [Title] (Phases X-Y)
...
```

---

### 3e. HAPPY_FLOW.md

Describes the ideal automation journey — no errors, no edge cases, just the golden path.

```markdown
# [Feature Name] — Happy Flow

## Overview
[One paragraph: the ideal scenario this feature automates — which site, which user journey]

## Step-by-Step Happy Flow

### Step 1: [Workflow step / action]
- **Action**: [action name in workflow JSON]
- **Stepper does**: [what glue + POM executes]
- **Browser state**: [what's visible / changed on the page]

### Step 2: [Next action]
...

## End State
[What the workflow has achieved after the happy flow completes]

## Success Indicators
- [ ] [Measurable indicator 1 — e.g., cart contains 3 items]
- [ ] [Measurable indicator 2 — e.g., checkout complete page visible]
```

---

### 3f. EDGE_CASES.md

Documents all known edge cases, error states, and failure modes.

```markdown
# [Feature Name] — Edge Cases

## Category 1: [Error type, e.g., Element Not Found]

### EC-1.1: [Specific edge case]
- **Trigger**: [What causes this — e.g., selector changes after site update]
- **Current behavior**: [What happens now — e.g., resolver falls back to CSS]
- **Expected behavior**: [What should happen]
- **Handled in**: [Phase X / Conv Y — e.g., add role-based cfg entry]

## Category 2: [Error type, e.g., Dynamic Content]
...

## Known Limitations
- [Limitation 1 — intentionally out of scope for this plan]
```

---

### 3g. ARCHITECTURE_PROPOSAL.md

A focused document on the technical approach and design decisions for this feature.

```markdown
# [Feature Name] — Architecture Proposal

## Problem Statement
[What automation gap or framework capability are we adding?]

## Proposed Solution
[High-level description — new site, new action type, new resolver strategy, etc.]

## Three-Layer Breakdown

```
Flow layer   (plans/$ARGUMENTS — JSON workflow)
     │  "action": "xx_action_name"
     ▼
Glue layer   (stepper/sites/<site>/pages/<action>.py)
     │  _build_pom(SomePage, …, page=page, resolver=resolver)
     ▼
POM layer    (poms/<site>/pages/<page>.py)
     │  _resolve_and_click_any(BUTTON_CFG)
     ▼
ElementResolver cascade → Playwright
```

## Key Design Decisions

### Decision 1: [Title]
- **Options considered**: A, B, C
- **Chosen**: A
- **Rationale**: [Why A wins — e.g., label resolver is more resilient than CSS]

### Decision 2: [Title]
...

## New Action Names
[List action names that will be registered — must match workflow JSON "action" keys]

## cfg List Design
[For each interactive element: which resolver keys, in what priority order, and why]

## Risks
- [Risk 1]: [Mitigation — e.g., site uses dynamic IDs → use role + label resolvers first]
- [Risk 2]: [Mitigation]
```

---

### 3h. FLOW_DIAGRAM.md

An ASCII flow diagram specific to **this feature** — shows how data flows through POM → Glue → Flow for the new actions only.

```markdown
# [Feature Name] — Flow Diagram

## [Primary Flow Name, e.g. "Happy Path: checkout workflow"]

```
[workflow JSON step]
        │  "action": "xx_step"
        ▼
[GlueAction._execute]
        │  _build_pom(Page, …, page=page, resolver=resolver)
        ▼
[POM method]
        │  _resolve_and_click_any(CFG_LIST)
        ▼
[ElementResolver cascade]
        │
        ├─ Phase 1: RoleResolver ──► unique match → click
        ├─ Phase 2: SemanticFilter (MiniLM)
        └─ Phase 3: AI Pick (Groq → Gemini → Claude)
```

## [Fallback / Error Flow]

```
[resolver finds 0 matches]
        │
        └─ raises ElementNotFoundError
                │
                └─ StepRunner catches → retry N times → fail step
```

## Component Legend

| Symbol | Meaning |
|--------|---------|
| [Name] | What this component does in this feature |
| ...    | ...                                       |
```

**Rules for FLOW_DIAGRAM.md:**
- Use ASCII only (boxes `[]`, arrows `──►`, branches `├─` / `└─`, vertical `│`)
- Show only the layers touched by this feature
- Include at minimum: happy path + resolver fallback path
- Label each arrow with the action name or cfg key being used
- Keep it narrow enough to read without horizontal scrolling (max ~70 chars wide)

---

## Conversation Splitting Rules

Follow these principles when deciding how to split phases into conversations:

1. **Each conversation must leave the codebase runnable.** End every prompt with a verify command.
2. **Hard cap: 4 conversations per folder.** If you need more, create part-2 folder.
3. **Natural seams for splits in this framework:**
   - POM layer first (cfg lists, locators, page methods) — everything depends on these
   - Glue layer second (action classes, `register()`) — depends on POM shape being stable
   - Flow layer (workflow JSON) + integration test — always last
   - Engine changes (new resolver strategy, new action base) — always their own conversation
4. **Explicit stop conditions.** Every prompt must say "Do NOT touch [X] yet."
5. **State handoff.** Later prompts reference: "Conversations 1-N are DONE (description)."
6. **Target 3-6 phases per conversation.** Too few = wasted context. Too many = context overload.
7. **Each prompt is self-contained.** References IMPLEMENTATION_PLAN.md for details but includes enough scope to run without it.

## Team-Safe Prompt Rules

Prompts MUST be resilient to codebase changes between conversations:

1. **NEVER reference specific line numbers.** Use function/class names instead:
   - BAD: `"Add cfg entry after line 42"`
   - GOOD: `"Add cfg entry to the Locators class in LoginPage (search for 'class Locators')"`
2. **NEVER reference exact test counts.** Use relative language:
   - BAD: `"All 12 existing tests must still pass"`
   - GOOD: `"All existing exam tests must still pass"`
3. **Reference code by class/method name:**
   - BAD: `"Modify the method at line 80"`
   - GOOD: `"Modify the _execute method in HotelSearchAction"`
4. **Always include the three-layer checklist** in prompts that touch glue or POM:
   - "cfg lists for all interactive elements (fill/click)"
   - "page=page, resolver=resolver on every POM constructor"
   - "No raw page.locator() in glue files"
5. **Include a recovery instruction in every prompt:**
   - `"If verification fails and the fix requires out-of-scope changes, stop and report. If fundamentally broken, rollback with git checkout on affected files and retry."`

## Step 4: Verify structure

After creating all files, verify:
- All **8 files** exist in `plans/$ARGUMENTS/`
- CONVERSATION_PROMPTS.md has ≤4 conversations (if more needed, create part-2 folder)
- CONVERSATION_PROMPTS.md conversation prompts reference correct phase numbers
- PROGRESS.md conversation table matches CONVERSATION_PROMPTS.md conversations
- Phase numbers are consistent across all files
- Verify commands use the correct site's workflow path or pytest command

## Step 5: Report

```
## Plans folder created: plans/$ARGUMENTS/

Files:
- USER_STORIES.md — N stories with acceptance criteria
- IMPLEMENTATION_PLAN.md — N phases across N conversations
- PROGRESS.md — Tracking table (all TODO)
- CONVERSATION_PROMPTS.md — N conversation prompts ready to paste (max 4)
- HAPPY_FLOW.md — Ideal automation journey
- EDGE_CASES.md — N edge cases documented
- ARCHITECTURE_PROPOSAL.md — Three-layer design decisions
- FLOW_DIAGRAM.md — ASCII flow diagram (happy path + resolver fallback)

To start implementing, open CONVERSATION_PROMPTS.md and paste Conversation 1.
```
