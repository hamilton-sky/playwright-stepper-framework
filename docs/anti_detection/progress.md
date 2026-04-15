---
title: Anti-Detection — Progress Tracker
type: progress
---

# Anti-Detection: Progress

Last updated: 2026-04-15

---

## Phase 1 — Critical (navigator.webdriver patch)

| Task | Status | Notes |
|---|---|---|
| Add `--disable-blink-features=AutomationControlled` to `main.py` | Done | Commit: hamilton/agent_to_agent branch |
| `add_init_script` in `main.py` after `new_page()` | Done | |
| Same two changes in `api.py` `StepperSession` | Done | |

---

## Phase 2 — High Impact (stealth + UA)

| Task | Status | Notes |
|---|---|---|
| Add `playwright-stealth` to `requirements.txt` | Pending | |
| Apply `stealth_async(page)` in `main.py` | Pending | |
| Apply `stealth_async(page)` in `api.py` | Pending | |
| Add `user_agent` to settings | Pending | |
| Pass `user_agent` to `new_context()` | Pending | |

---

## Phase 3 — Proxy Support

| Task | Status | Notes |
|---|---|---|
| Add proxy env vars to config | Pending | |
| Wire proxy into `context_kwargs` in `main.py` | Pending | |
| Wire proxy into `StepperSession` | Pending | |
| Document env vars in README | Pending | |

---

## Phase 4 — CAPTCHA Solver

| Task | Status | Notes |
|---|---|---|
| `SolveCaptchaAction` strategy | Pending | |
| Register in `ActionRegistry` | Pending | |
| `CaptchaDetectorStrategy` resolver | Pending | |
| Hook into step runner | Pending | |

---

## Phase 5 — TLS Fingerprint (optional)

| Task | Status | Notes |
|---|---|---|
| Evaluate `patchright` compatibility | Pending | Only needed for Cloudflare/Akamai targets |
| Swap playwright → patchright imports | Pending | |

---

## Verification Checklist

- [ ] Phase 1: `navigator.webdriver` returns `undefined` in DevTools after fix
- [ ] Phase 2: UA string contains no `"HeadlessChrome"`
- [ ] Phase 2: `navigator.plugins.length > 0`
- [ ] Phase 3: Requests route through proxy when `PROXY_SERVER` is set
- [ ] Phase 4: `solve_captcha` action executes successfully on a test page
- [ ] Phase 5: JA3 fingerprint matches real Chrome
