---
name: next-phase
description: Execute the next incomplete conversation of a feature plan. Reads CONVERSATION_PROMPTS.md, checks PROGRESS.md, and implements the next TODO conversation with verification. Supports auto-flow mode (execute → commit → guide to next conv).
argument-hint: "[plan-folder-name, e.g., refactor-main]"
---

Parse `$ARGUMENTS`: the first word is the **plan folder name**, and if a second word "auto" is present, that signals non-interactive auto-flow mode. For example, `/next-phase refactor-main auto` → plan = `refactor-main`, auto mode = true.

## Step 0: Execution Mode Selection

Check if `$ARGUMENTS` contains the word "auto". If so, skip the menu and set `autoFlow = true` immediately — this is the non-interactive path used by `scripts/auto-flow.sh`. Also skip Step 1 dirty-check prompts and Step 4 "Proceed? (y/n)" confirmation — just execute.

Otherwise, ask the user to choose:

```
Choose execution mode:

1. Auto-flow — execute conversation, verify, commit, guide to next
   (Best for sequential conversations. Auto-commits on success.)

2. Manual — execute current conversation only, you handle commit + next steps
   (Best for exploration or when you want to review before committing.)
```

Wait for user selection. Default to Manual if unclear.

## Step 1: Pre-flight check

Run `git status` (without -uall flag).

- **If working directory is clean:** Proceed to Step 2.
- **If there are uncommitted changes:** STOP. Report to user:
  ```
  Working directory is not clean. Found uncommitted changes:
  [list modified files]

  Each conversation must start from a known state. Options:
  (a) Commit current changes first
  (b) Stash them: git stash
  (c) Proceed anyway (not recommended)
  ```
  Wait for user decision before continuing. In auto-flow mode, stop immediately.

## Step 2: Locate the plan folder

Find the plan folder at `plans/$PLAN/`. If it doesn't exist, list all `plans/*/` folders and ask which one the user meant.

## Step 3: Read current state

Read these files:

1. **`plans/$PLAN/PROGRESS.md`** — Find the first row in the "Conversation Breakdown" table with status **TODO**. That is the next target conversation. Also check overall Status — if COMPLETE, stop and report.

2. **`plans/$PLAN/CONVERSATION_PROMPTS.md`** — Find the section for the target conversation number. Extract:
   - The full prompt (everything inside the ` ``` ` block)
   - The verify command (from the prompt or the "Expected output" line)
   - Files touched (listed after the prompt block)

## Step 4: Confirm scope

Report to the user before starting:

```
## Next: Conversation N — [title]
- Mode: [Auto-flow / Manual]
- Scope: [files listed in CONVERSATION_PROMPTS.md]
- Verify: [command]

Proceed? (y/n)
```

In auto-flow mode, skip this and proceed immediately.

## Step 5: Implement

Execute exactly what the conversation prompt specifies:

1. Read each file that will be modified
2. Make changes following the prompt's specifications exactly
3. Follow all project conventions from CLAUDE.md and .claude/rules/
4. Stay strictly within the conversation's scope — do NOT touch files outside the listed scope
5. **No silent refactoring**: do not rename, reformat, or clean up anything outside what the prompt explicitly requires

## Step 6: Verify

Run the verify command from the conversation prompt. Example:
```bash
python stepper/main.py --workflow stepper/sites/openlibrary/workflows/search_and_add.json
```

If verification fails, fix the issues before proceeding. If the fix requires out-of-scope changes, STOP and report:
```
Verification failed. The fix requires changes to [file] which is outside this conversation's scope.
Options: (a) expand scope, (b) rollback with git checkout and retry
```

In auto-flow mode, attempt up to 2 fixes. If still failing, switch to manual mode and stop.

## Step 7: Update PROGRESS.md

After successful verification, update `plans/$PLAN/PROGRESS.md`:

1. Change the target conversation's `| TODO |` → `| DONE |`
2. Change all Phase Detail rows belonging to this conversation from `TODO` → `DONE`
3. If all conversations are now DONE, change overall `Status: NOT STARTED` or `Status: IN PROGRESS` → `Status: COMPLETE`

## Step 8: Commit + Next Steps

### If Auto-flow mode (`autoFlow = true`):

1. **Auto-commit** all changes:
   ```bash
   git add [all files modified] plans/$PLAN/PROGRESS.md
   git commit -m "feat: $PLAN conv N done

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
   ```

2. **Check what's next** — read PROGRESS.md for the next TODO conversation.

3. **If more conversations remain:**
   ```
   ✅ Conv N — DONE and committed.

   📋 Next up: Conv N+1 — [scope summary]

   Context is accumulating. To continue with a fresh session:
   👉 Run: /clear
   👉 Then: /next-phase $PLAN

   Or for full automation from a terminal:
   👉 Run: bash scripts/auto-flow.sh $PLAN
   ```

4. **If all conversations are DONE:**
   ```
   ✅ All conversations COMPLETE for $PLAN!
   ```

### If Manual mode (`autoFlow = false`):

```
## Completed: Conv N — [title]
- Files modified: [list]
- Verification: passed
- Next up: Conv N+1 — [title]

Remember to commit before starting the next conversation.
```

## Edge Cases

- **All conversations DONE**: Report "Plan $PLAN is already COMPLETE."
- **No CONVERSATION_PROMPTS.md**: Fall back to reading IMPLEMENTATION_PLAN.md directly for the next TODO phase.
- **Blocked conversation**: Report the blocker and stop.
