"""
engine/browser/anti_detection.py — Deterministic anti-detection service.

Applies browser-level defences at context and page creation time.
All methods are stateless and called from api.py (StepperSession.__aenter__).

Phases covered:
  1  JS signal patching    — navigator.webdriver removed via add_init_script
  2  UA spoofing + stealth — realistic UA + playwright-stealth patches
  3  Proxy support         — new_context proxy kwarg from env
  5  TLS fingerprint       — patchright drop-in swap (falls back to playwright)

Phase 4 (CAPTCHA / external service) is intentionally excluded — it is
non-deterministic and handled separately as a workflow action step.

Configuration via environment variables (all optional):
  BROWSER_USER_AGENT   Override the User-Agent string
  PROXY_SERVER         Proxy endpoint, e.g. http://proxy.example.com:8080
  PROXY_USERNAME       Proxy auth username
  PROXY_PASSWORD       Proxy auth password
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class AntiDetection:
    """
    Stateless service — all methods are static.
    Call order in StepperSession.__aenter__:

      1. async_playwright = AntiDetection.get_playwright()
      2. context_kwargs.update(AntiDetection.context_kwargs())
      3. await AntiDetection.apply_page_patches(page)
    """

    @staticmethod
    def get_playwright():
        """
        Phase 5 — return patchright's async_playwright if installed,
        otherwise fall back to standard playwright.
        """
        try:
            from patchright.async_api import async_playwright
            logger.debug("AntiDetection: using patchright (TLS fingerprint patched)")
        except ImportError:
            from playwright.async_api import async_playwright
            logger.debug("AntiDetection: patchright not installed, using playwright")
        return async_playwright

    @staticmethod
    def context_kwargs() -> dict:
        """
        Phase 2+3 — return extra kwargs to merge into browser.new_context().

        Always sets user_agent.
        Adds proxy block only when PROXY_SERVER env var is present.
        """
        kwargs: dict = {
            "user_agent": os.environ.get("BROWSER_USER_AGENT", _DEFAULT_UA)
        }

        proxy_server = os.environ.get("PROXY_SERVER", "").strip()
        if proxy_server:
            proxy: dict = {"server": proxy_server}
            username = os.environ.get("PROXY_USERNAME", "").strip()
            if username:
                proxy["username"] = username
                proxy["password"] = os.environ.get("PROXY_PASSWORD", "")
            kwargs["proxy"] = proxy
            logger.debug("AntiDetection: proxy configured → %s", proxy_server)

        return kwargs

    @staticmethod
    async def apply_page_patches(page) -> None:
        """
        Phase 1+2 — apply JS-level patches to a freshly created page.

        Always runs:
          - navigator.webdriver patch (Phase 1)

        Runs if installed:
          - playwright-stealth full patch set (Phase 2)
            Install with: pip install playwright-stealth
            If absent, a warning is logged and execution continues normally.
        """
        # Phase 1 — always active, no external dependency
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Phase 2 — enhancement, graceful degradation if library absent
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
            logger.debug("AntiDetection: playwright-stealth patches applied")
        except ImportError:
            logger.warning(
                "AntiDetection: playwright-stealth not installed — "
                "JS signal patching is partial (webdriver only). "
                "Install with: pip install playwright-stealth"
            )

    # ── Phase 4 — CAPTCHA detection ────────────────────────────────────────────

    #: Known CAPTCHA selectors — checked in priority order (cheapest first).
    _CAPTCHA_SELECTORS: list[tuple[str, str]] = [
        ("iframe[src*='recaptcha']",          "reCAPTCHA iframe"),
        ("iframe[src*='hcaptcha']",            "hCaptcha iframe"),
        ("iframe[src*='challenges.cloudflare']","Cloudflare Turnstile iframe"),
        (".g-recaptcha",                       "reCAPTCHA widget"),
        (".h-captcha",                         "hCaptcha widget"),
        ("[data-sitekey]",                     "CAPTCHA sitekey attribute"),
        ("#cf-challenge-running",              "Cloudflare challenge"),
        ("#cf-please-wait",                    "Cloudflare please-wait"),
    ]

    @staticmethod
    async def detect_captcha(page) -> str | None:
        """
        Phase 4 — deterministic CAPTCHA detection.

        Checks a prioritised list of known CAPTCHA selectors against the current page.
        Returns a human-readable description string if a CAPTCHA is found, else None.

        No external service, no cost. Call this before each step in StepRunner.

        Example:
            captcha = await AntiDetection.detect_captcha(page)
            if captcha:
                raise RuntimeError(f"CAPTCHA detected: {captcha}")
        """
        for selector, label in AntiDetection._CAPTCHA_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element:
                    logger.warning("AntiDetection: CAPTCHA detected — %s (%s)", label, selector)
                    return label
            except Exception:
                # Page may be mid-navigation; skip this selector silently
                continue
        return None
