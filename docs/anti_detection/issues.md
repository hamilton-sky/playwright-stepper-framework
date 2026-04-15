---
title: Anti-Detection — Known Gaps
type: issues
---

# Anti-Detection: Known Issues

These are the bot-detection signals the framework currently does NOT suppress.
Each is a distinct attack surface that sites use to identify automation.

---

## ISSUE-01 — navigator.webdriver flag (FIXED)
**Severity:** Critical  
**Status:** Fixed in `stepper/main.py` and `stepper/engine/runner/api.py`

Playwright sets `navigator.webdriver = true` in every page context.
Any site running `if (navigator.webdriver) { block(); }` will immediately
detect automation — no CAPTCHA or heuristics needed.

---

## ISSUE-02 — No browser stealth / JS automation signal patching
**Severity:** High  
**Status:** Open

Beyond `navigator.webdriver`, Playwright leaks automation through:
- `window.chrome` missing (real Chrome sets it)
- `navigator.plugins` is empty (real browsers have plugins)
- `navigator.languages` is `["en-US"]` only
- `window.Notification.permission` is `"default"` always
- WebGL renderer reports `"Google SwiftShader"` in headless mode

Libraries like `playwright-stealth` (Python: `playwright_stealth`) patch all
of these at once via `add_init_script`.

---

## ISSUE-03 — No User-Agent spoofing
**Severity:** High  
**Status:** Open

Default Playwright User-Agent includes `"HeadlessChrome"` when running headless.
Real users never have `HeadlessChrome` in their UA string — it is a hard signal.
Even in headed mode, the UA reports the exact Playwright-controlled Chrome version,
which may not match realistic desktop UAs from real users.

---

## ISSUE-04 — No proxy rotation
**Severity:** Medium  
**Status:** Open

All requests originate from the same IP address.
Consequences:
- IP-based rate limiting hits after N requests
- Datacenter IP ranges are blocked outright by many sites
- No geographic distribution to mimic organic traffic

---

## ISSUE-05 — No CAPTCHA solver integration
**Severity:** Medium (for current target sites) / Critical (for protected sites)  
**Status:** Open

No mechanism to:
- Detect a CAPTCHA widget has appeared in the DOM
- Pause and route to an external solving service (2captcha, Anti-Captcha, CapSolver)
- Inject the solved token back and resume the workflow

Current target sites (OpenLibrary, SauceDemo) do not serve CAPTCHAs,
so this is not blocking — but it prevents the framework from being used
on any protected site.

---

## ISSUE-06 — No TLS fingerprint masking
**Severity:** Low–Medium  
**Status:** Open

Playwright's Chromium produces a distinct JA3 TLS fingerprint.
Advanced bot-detection services (Cloudflare, Akamai) compare this fingerprint
against the claimed User-Agent. Mismatches (e.g., UA says "Chrome 120" but
JA3 matches Playwright's Chromium build) are flagged.
This requires using a patched Chromium build (e.g., `patchright`) to fix fully.
