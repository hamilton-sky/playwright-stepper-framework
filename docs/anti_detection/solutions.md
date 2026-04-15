---
title: Anti-Detection — Solutions
type: solutions
---

# Anti-Detection: Solutions

One solution per issue. Each solution fits the existing framework
architecture — no new layers, no breaking changes.

---

## SOL-01 — Patch navigator.webdriver (DONE)

**Fixes:** ISSUE-01  
**Files changed:** `stepper/main.py`, `stepper/engine/runner/api.py`

**What was added:**

1. Browser launch flag — tells Chrome to not inject the automation flag:
```python
args=["--disable-blink-features=AutomationControlled"]
```

2. Init script — patches the JS property on every new page before any
   site script runs:
```python
await page.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)
```

Both changes were applied to the two launch sites:
- `stepper/main.py` — standalone workflow runner
- `stepper/engine/runner/api.py` — `StepperSession` (used by tests)

---

## SOL-02 — Full stealth patching with playwright-stealth

**Fixes:** ISSUE-02  
**Approach:** Install `playwright-stealth` and apply it after page creation.

```bash
pip install playwright-stealth
```

In both `main.py` and `api.py`, after `page = await context.new_page()`:

```python
from playwright_stealth import stealth_async
await stealth_async(page)
```

This patches `window.chrome`, `navigator.plugins`, `navigator.languages`,
`WebGL renderer`, `Notification.permission`, and ~15 other signals in one call.

If `playwright-stealth` is not available (import error), fall through silently —
the `navigator.webdriver` fix from SOL-01 is already applied independently.

---

## SOL-03 — Realistic User-Agent injection

**Fixes:** ISSUE-03  
**Approach:** Pass `user_agent` in `new_context()` kwargs.

```python
REAL_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
context_kwargs["user_agent"] = REAL_UA
```

Best practice: store UA strings in `poms/shared/interfaces.py` or in a
site config value, not hardcoded in `main.py`.
A rotating UA pool gives further coverage.

---

## SOL-04 — Proxy support via context kwargs

**Fixes:** ISSUE-04  
**Approach:** Playwright's `new_context()` accepts a `proxy` dict natively.

```python
if settings.proxy_server:
    context_kwargs["proxy"] = {
        "server": settings.proxy_server,          # e.g. "http://1.2.3.4:8080"
        "username": settings.proxy_username,       # optional
        "password": settings.proxy_password,       # optional
    }
```

Add `proxy_server`, `proxy_username`, `proxy_password` fields to the
settings dataclass and read from env vars (`PROXY_SERVER` etc.).
No changes needed in the POM or glue layers.

---

## SOL-05 — CAPTCHA solver integration

**Fixes:** ISSUE-05  
**Approach:** Two components — a detector and a solver action.

**Detector** — new `ResolverStrategy` or a separate utility called
before each step:
```python
captcha_selectors = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    ".cf-turnstile",
]
```
If any selector matches, raise `CaptchaDetectedError`.

**Solver action** — new `ActionStrategy` named `solve_captcha`:
```python
class SolveCaptchaAction(ActionStrategy):
    action_name = "solve_captcha"

    async def _execute(self, page, step, resolver, context):
        sitekey = step.params.get("sitekey")
        service = TwoCaptchaClient(api_key=os.environ["CAPTCHA_API_KEY"])
        token   = await service.solve_recaptcha(sitekey, page.url)
        await page.evaluate(
            f"document.getElementById('g-recaptcha-response').value = '{token}'"
        )
```

Register in `ActionRegistry` and call from workflow JSON as a step.

---

## SOL-06 — TLS fingerprint masking

**Fixes:** ISSUE-06  
**Approach:** Replace Playwright's Chromium with `patchright`.

```bash
pip install patchright
patchright install chromium
```

```python
from patchright.async_api import async_playwright
```

`patchright` is a drop-in replacement — same API, patched Chromium binary
with a realistic JA3 fingerprint. No other code changes needed.

This is an optional advanced step — only necessary against
Cloudflare Enterprise / Akamai Bot Manager targets.
