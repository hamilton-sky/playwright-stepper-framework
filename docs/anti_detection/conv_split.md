---
title: Anti-Detection — Conversation Context Split
type: conv_split
---

# Conversation Split: Anti-Detection Topic

This file records the key decisions and findings from the conversation
that produced this folder. Use it to resume context in a new session
without re-deriving everything.

---

## What was asked

1. How does the project deal with CAPTCHA?
2. Explain CAPTCHA and all related bot-detection concepts.
3. How does the project handle them?
4. Fix the `navigator.webdriver` leak.
5. Create this documentation folder.

---

## Key findings from codebase analysis

| Signal | Project behaviour |
|---|---|
| `navigator.webdriver` | Was leaking — **now fixed** (Phase 1) |
| `slow_mo` / `Delays` | Present — actions are paced to look human |
| `storage_state` | Present — session cookies persisted across runs to avoid re-login |
| Semantic locators | Present — `get_by_role`, `get_by_label` used everywhere |
| Viewport dimensions | Present — `1280×800` set explicitly |
| Stealth JS patching | Missing |
| User-Agent spoofing | Missing |
| Proxy rotation | Missing |
| CAPTCHA solver | Missing |
| TLS fingerprint | Missing |

## Why these gaps don't matter today

Target sites — OpenLibrary, SauceDemo, phpTravels test environment — are
open-access or purpose-built testing sandboxes. None deploy CAPTCHA,
IP-rate-limiting, or fingerprint checks. The framework's current defences
(`slow_mo`, `storage_state`, semantic locators, viewport) are sufficient
for these targets.

## Decisions made

- Phase 1 fix applied immediately — zero risk, pure upside.
- Phases 2–5 documented but not yet implemented — not needed for current targets.
- Architecture is compatible with all future phases:
  - New resolver strategy for CAPTCHA detection (fits existing Strategy pattern)
  - New `ActionStrategy` for `solve_captcha` (fits existing Template Method)
  - Proxy / UA / stealth — all injected at `new_context()` / `add_init_script()` level, no POM changes

## Files changed in Phase 1

- [stepper/main.py](../../stepper/main.py) — lines ~142 and ~193–196
- [stepper/engine/runner/api.py](../../stepper/engine/runner/api.py) — lines ~106 and ~115–118

## Next conversation entry point

Start from `progress.md` — check which phases are still Pending and
continue with Phase 2 (playwright-stealth + UA spoofing) as the
next highest-impact, lowest-effort step.
