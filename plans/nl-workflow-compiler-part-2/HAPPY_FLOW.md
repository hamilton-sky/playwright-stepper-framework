# NL Workflow Compiler Part 2 — Happy Flow

## Overview

The user wants to automate a full SauceDemo purchase across 4 pages (login → inventory → cart → checkout). With `--live`, the AI sees each page's real DOM rather than inferring blind, producing accurate steps for every stage.

## Step-by-Step Happy Flow

### Step 1: User runs live command
- **Command**: `python stepper/main.py --live "log in as standard_user, add Sauce Labs Backpack to cart, checkout" --site saucedemo --show`
- **Stepper does**: Launches browser, navigates to `https://www.saucedemo.com`
- **Browser state**: Login page loaded

### Step 2: Page 1 — Login page
- **Stepper does**: ARIA snapshot (≤50 nodes → full strategy) → AI plans: fill username, fill password, click login button
- **AI call**: ~600 tokens (Groq, ~1s)
- **Browser state**: Executes 3 steps → navigation fires → inventory page loads

### Step 3: Page 2 — Inventory page
- **Stepper does**: ARIA snapshot (~80 nodes → interactive_only) → AI receives: sort dropdown, product buttons, add-to-cart buttons → plans: click "Add to cart" for Backpack
- **AI call**: ~400 tokens (Groq, ~1s)
- **Browser state**: Backpack added to cart → no full navigation (SPA partial update) → stall counter resets

### Step 4: Page 2 continued — AI returns empty steps (intent for this page done)
- **Stepper does**: AI returns [] → loop moves to next page trigger
- **User clicks cart icon** (or AI planned a "navigate to cart" step) → navigation fires

### Step 5: Page 3 — Cart page
- **Stepper does**: ARIA snapshot → AI plans: verify Backpack in cart, click Checkout
- **AI call**: ~300 tokens
- **Browser state**: Checkout info page loads

### Step 6: Page 4 — Checkout info
- **Stepper does**: ARIA snapshot → AI plans: fill first name, last name, postal, click Continue
- **AI call**: ~350 tokens
- **Browser state**: Checkout overview loads → Continue → order complete

### Step 7: Loop ends
- **Stepper does**: AI returns [] on completion page → loop exits
- **All steps collected**: ~12 steps across 4 pages
- **Saves**: `stepper/sites/saucedemo/workflows/live_20260421_143200.json`
- **Terminal**:
  ```
  [LiveLoop] 4 page cycles, 12 total steps
  Workflow saved to: stepper/sites/saucedemo/workflows/live_20260421_143200.json
  Run deterministically: python stepper/main.py --workflow stepper/sites/saucedemo/workflows/live_20260421_143200.json
  ```

## End State

A multi-page workflow JSON exists. Every subsequent run is deterministic and zero-AI-token. Self-healing fires only if a specific locator breaks on a future site update.

## Success Indicators
- [ ] 3–5 AI calls total (one per page, not one per step)
- [ ] live_*.json created and valid JSON
- [ ] Saved JSON runs to checkout-complete with `--workflow` flag
- [ ] Total token cost for compile < 2500 tokens (vs ~30K for a full Browser Use run)
- [ ] No AI calls in logs during the `--workflow` deterministic run
