---
title: Anti-Detection — Implementation Plan
type: plan
---

# Implementation Plan: Anti-Detection Hardening

Ordered by impact vs. effort. Each phase is independently deployable.

---

## Phase 1 — Critical (< 1 hour) — DONE

**Goal:** Remove the one signal that causes instant detection on any modern site.

| Step | File | Change |
|---|---|---|
| 1.1 | `stepper/main.py` | Add `--disable-blink-features=AutomationControlled` to launch args |
| 1.2 | `stepper/main.py` | `add_init_script` to undefine `navigator.webdriver` after `new_page()` |
| 1.3 | `stepper/engine/runner/api.py` | Same two changes for `StepperSession` |

**Acceptance criteria:**
```js
// Run in browser DevTools after launch — must return undefined
navigator.webdriver  // undefined
```

---

## Phase 2 — High Impact (2–4 hours)

**Goal:** Eliminate the remaining JS automation signals and the headless UA.

| Step | File | Change |
|---|---|---|
| 2.1 | `requirements.txt` | Add `playwright-stealth` |
| 2.2 | `stepper/main.py` | `from playwright_stealth import stealth_async; await stealth_async(page)` |
| 2.3 | `stepper/engine/runner/api.py` | Same stealth call |
| 2.4 | `poms/shared/interfaces.py` | Add `user_agent: str` field to a new `BrowserSettings` dataclass |
| 2.5 | `poms/openLibrary/config.py` | Populate `user_agent` from env `BROWSER_USER_AGENT` with a sane default |
| 2.6 | `stepper/main.py` | Pass `user_agent` into `context_kwargs` |

**Acceptance criteria:**
- UA logged at startup contains no `"HeadlessChrome"`
- `navigator.plugins.length > 0` in init script check

---

## Phase 3 — Medium Impact (4–8 hours)

**Goal:** Support proxy rotation to avoid IP-based blocks.

| Step | File | Change |
|---|---|---|
| 3.1 | `poms/openLibrary/config.py` | Add `proxy_server`, `proxy_username`, `proxy_password` env vars |
| 3.2 | `poms/shared/interfaces.py` | Add proxy fields to settings dataclass |
| 3.3 | `stepper/main.py` | Populate `context_kwargs["proxy"]` when `proxy_server` is set |
| 3.4 | `stepper/engine/runner/api.py` | Same proxy wiring in `StepperSession` |
| 3.5 | `README.md` | Document new env vars |

**Acceptance criteria:**
- `PROXY_SERVER=http://...` env var causes all requests to route through proxy
- Absent env var — no proxy, no error

---

## Phase 4 — Conditional (8–16 hours)

**Goal:** Enable the framework to handle CAPTCHA-protected target sites.

| Step | File | Change |
|---|---|---|
| 4.1 | `stepper/engine/actions/strategies.py` | New `SolveCaptchaAction(ActionStrategy)` |
| 4.2 | `stepper/engine/actions/factory.py` | Register `solve_captcha` in `build_default_registry()` |
| 4.3 | `stepper/engine/resolvers/` | New `CaptchaDetectorStrategy` — raises before step if widget found |
| 4.4 | `stepper/engine/runner/step_runner.py` | Hook `CaptchaDetectorStrategy` check into step loop |
| 4.5 | `.env.example` | Add `CAPTCHA_API_KEY` |

**Acceptance criteria:**
- Workflow JSON with `{"action": "solve_captcha", "params": {"sitekey": "..."}}` executes without error
- When no CAPTCHA is on screen, step is a no-op

---

## Phase 5 — Advanced / Optional (half-day)

**Goal:** Pass TLS fingerprint checks on enterprise bot-detection (Cloudflare, Akamai).

| Step | File | Change |
|---|---|---|
| 5.1 | `requirements.txt` | Replace `playwright` with `patchright` |
| 5.2 | `stepper/main.py` | `from patchright.async_api import async_playwright` |
| 5.3 | `stepper/engine/runner/api.py` | Same import swap |
| 5.4 | CI / install docs | `patchright install chromium` instead of `playwright install` |

**Acceptance criteria:**
- JA3 fingerprint check (e.g. `tls.peet.ws`) shows a realistic Chrome fingerprint
- All existing tests still pass
