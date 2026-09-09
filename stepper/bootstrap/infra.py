from __future__ import annotations
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SiteRegistrationError(RuntimeError):
    """
    Raised when one or more sites fail to register their actions.

    Carries every failure, not just the first, so one run surfaces all of them —
    same principle as PlanValidator.
    """

    def __init__(self, message: str, failures: dict[str, BaseException]):
        super().__init__(message)
        self.failures = failures


def build_resolver(use_visual_ai: bool):
    from engine.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
    ai_client = None
    if use_visual_ai:
        import anthropic
        ai_client = anthropic.Anthropic()
    factory = DefaultResolverFactory()
    return ElementResolver(
        strategies=factory.build_cascade(),
        ai_client=ai_client,
        use_visual_ai=use_visual_ai,
    )


async def launch_browser(pw, cfg_browser: str, headless: bool, slow_mo: int):
    launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
    return await launchers.get(cfg_browser, pw.chromium).launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled"],
    )


def register_all_sites(registry, stepper_root: Path, screenshots_dir=None) -> None:
    """
    Import every ``sites/*/register.py`` and let it register its actions.

    A site that fails to import used to be logged as a warning and skipped, which
    turned a typo in one glue file into ``ValueError: Unknown action: 'sd_login'``
    at step 1 — a message that points at the workflow instead of the real cause.
    Failures are now collected and raised together.

    Raises:
        SiteRegistrationError: if any site failed to register.
    """
    failures: dict[str, BaseException] = {}

    for reg_path in sorted((stepper_root / "sites").glob("*/register.py")):
        site = reg_path.parent.name
        try:
            mod = importlib.import_module(f"sites.{site}.register")
            mod.register(registry, screenshots_dir=screenshots_dir)
        except Exception as exc:
            # Full traceback at ERROR — the summary below only carries the message.
            logger.error("Site '%s' failed to register", site, exc_info=True)
            failures[site] = exc

    if failures:
        detail = "\n".join(
            f"  - {site}: {type(exc).__name__}: {exc}" for site, exc in failures.items()
        )
        raise SiteRegistrationError(
            f"{len(failures)} site(s) failed to register their actions:\n{detail}\n"
            "Their actions are not available, so any workflow using them would fail "
            "with 'Unknown action'. Fix the error above, not the workflow.",
            failures,
        )
