---
name: retro
description: Run a retrospective on a completed feature plan. Reads PROGRESS.md and CONVERSATION_PROMPTS.md, asks 3 focused questions, and writes RETRO.md to feed future storm sessions.
argument-hint: "[plan-folder-name, e.g., add-saucedemo-checkout]"
---

## Skill Contract

**Consumes:** `plans/$ARGUMENTS/PROGRESS.md` + `plans/$ARGUMENTS/CONVERSATION_PROMPTS.md`
**Produces:** `plans/$ARGUMENTS/RETRO.md`
**Consumed by:** `storm` skill (user pastes RETRO.md as context for next storm session)

Run a retrospective on the **$ARGUMENTS** feature plan.

## Step 1: Read the plan

Read both files:
1. `plans/$ARGUMENTS/PROGRESS.md` — overall status, what was completed
2. `plans/$ARGUMENTS/CONVERSATION_PROMPTS.md` — the prompts that were used

If the plan folder doesn't exist, list all `plans/*/` folders and ask which one the user meant.
If PROGRESS.md status is not COMPLETE, warn: "This plan is not marked COMPLETE — retro may be incomplete."

## Step 2: Ask 3 questions

Ask these three questions, one at a time. Wait for an answer before asking the next:

**Q1:** "Looking at the conversation prompts — were any conversations too big (needed mid-conversation scope cuts) or too small (finished too fast with leftover context)?"

**Q2:** "Did anything break unexpectedly during implementation that the plan didn't anticipate? Any three-layer violations, resolver issues, or test failures that surprised you?"

**Q3:** "What would you tell yourself before starting this feature — the one thing the plan should have said but didn't?"

## Step 3: Write RETRO.md

Write `plans/$ARGUMENTS/RETRO.md`:

```markdown
# [Feature Name] — Retrospective

## Plan Quality
**Conversation sizing:** [too big / too small / good — from Q1]
**Surprises:** [from Q2]
**Missing from plan:** [from Q3]

## What Worked
- [extract from user answers]

## What to Improve Next Time
- [extract from user answers — actionable, specific]

## Seed for Next Storm
> Paste this block as context when starting the next related storm session:
[2-3 sentence summary of the key learning from this retro]
```

## Step 4: Report

```
Retro written: plans/$ARGUMENTS/RETRO.md

To use in your next storm session:
1. Run /storm
2. Paste the "Seed for Next Storm" block from RETRO.md as opening context
```
