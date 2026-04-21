# NL Workflow Compiler — Happy Flow

## Overview

The user wants to automate a SauceDemo purchase but doesn't want to write JSON. They run one compile command, get a workflow file, and from that point on every execution is deterministic and free of AI calls.

## Step-by-Step Happy Flow

### Step 1: User runs compile command
- **Command**: `python stepper/main.py --compile "log in as standard_user, add Sauce Labs Backpack to cart, checkout" --site saucedemo`
- **Stepper does**: Launches headless browser, navigates to `https://www.saucedemo.com`
- **Browser state**: Login page loaded

### Step 2: ARIA snapshot
- **Stepper does**: Calls `page.accessibility.snapshot()` — returns structured tree of roles, names, labels
- **Browser state**: Unchanged (read-only operation)
- **Output**: ~30–80 ARIA nodes (login page is simple)

### Step 3: AI call (Groq first)
- **Stepper does**: PromptBuilder assembles system prompt (cfg rules + action registry) + user prompt (ARIA tree + intent) → AIService.chat(task_type="compile") → Groq responds in ~2s
- **Cost**: ~800–1200 tokens total (Groq free tier: 14,400 req/day)

### Step 4: Parse + validate
- **Stepper does**: OutputParser strips fences, parses JSON array, checks each action name against registry
- **Output**: 3–5 steps with cfg lists populated from ARIA roles/names

### Step 5: Save workflow JSON
- **Stepper does**: Writes to `stepper/sites/saucedemo/workflows/compiled.json`
- **Terminal output**:
  ```
  Workflow saved to: stepper/sites/saucedemo/workflows/compiled.json
  Run it with: python stepper/main.py --workflow stepper/sites/saucedemo/workflows/compiled.json
  ```

### Step 6: User runs the compiled workflow
- **Command**: `python stepper/main.py --workflow stepper/sites/saucedemo/workflows/compiled.json --show`
- **Stepper does**: JsonFilePlanner loads JSON → StepRunner executes deterministically → resolver cascade fires (no AI)
- **Browser state**: Login → inventory → cart → checkout complete

## End State

A compiled workflow JSON exists on disk. Every future run is deterministic. Self-healing fires only if a locator breaks (e.g., site redesign) — not on every run.

## Success Indicators
- [ ] `compiled.json` created in under 10 seconds
- [ ] File passes JSON lint
- [ ] All action names in compiled.json exist in the registry
- [ ] Workflow runs to completion with `--workflow` flag
- [ ] No AI calls visible in logs during the `--workflow` run (unless `--heal` triggers)
