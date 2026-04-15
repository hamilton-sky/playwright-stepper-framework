---
title: Anti-Detection — User Stories
type: user_story
---

# Anti-Detection: User Stories

---

## US-01 — Undetected Headless Browser

**As a** test automation engineer,  
**I want** the framework to run without triggering browser bot-detection,  
**So that** automated tests reach the real application UI instead of being
blocked or served a CAPTCHA page.

**Acceptance criteria:**
- `navigator.webdriver` returns `undefined` on every page
- The browser UA string does not contain `"HeadlessChrome"`
- Standard JS bot-detection checks (`window.chrome`, `navigator.plugins`) pass
- All existing workflows and tests continue to pass

**Priority:** Critical  
**Effort:** Phase 1 (done) + Phase 2 (~3h)

---

## US-02 — Proxy Configuration

**As a** test automation engineer running high-volume or geographically
distributed tests,  
**I want** to configure a proxy server via environment variable,  
**So that** all browser traffic routes through the proxy without changing
workflow JSON or POM code.

**Acceptance criteria:**
- Setting `PROXY_SERVER=http://host:port` causes all page requests to go through that proxy
- If `PROXY_SERVER` is not set, no proxy is used and there is no error
- Proxy credentials (`PROXY_USERNAME`, `PROXY_PASSWORD`) are optional

**Priority:** Medium  
**Effort:** Phase 3 (~4h)

---

## US-03 — CAPTCHA-Aware Workflow Execution

**As a** test automation engineer targeting CAPTCHA-protected pages,  
**I want** the framework to detect when a CAPTCHA appears and either
solve it automatically or pause for manual intervention,  
**So that** workflows do not fail silently or get stuck on challenge pages.

**Acceptance criteria:**
- When a reCAPTCHA or hCaptcha widget is detected in the DOM, an actionable
  error is raised rather than a generic timeout
- A `solve_captcha` workflow step can be added before any form submission on
  a protected page
- The step calls a configurable external solving service (key from `CAPTCHA_API_KEY`)
- On success, the solved token is injected and the workflow continues

**Priority:** Low (current sites are CAPTCHA-free)  
**Effort:** Phase 4 (~8h)

---

## US-04 — Enterprise Bot-Detection Bypass (TLS)

**As a** test automation engineer targeting Cloudflare- or Akamai-protected sites,  
**I want** the framework to present a realistic TLS fingerprint,  
**So that** requests are not blocked at the network edge before the page
even loads.

**Acceptance criteria:**
- JA3 fingerprint check (e.g. via `tls.peet.ws`) shows a realistic Chrome fingerprint
- All existing tests pass with the patched browser
- Drop-in swap — no workflow JSON or POM changes required

**Priority:** Optional / advanced  
**Effort:** Phase 5 (half-day)
