from __future__ import annotations
import importlib
import json
import logging
import os
import sys
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
    from stepper.engine.resolvers.element_resolver import ElementResolver, DefaultResolverFactory
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
    """
    Launch the configured browser.

    BROWSER_EXECUTABLE_PATH overrides the binary Playwright would pick — see
    poms.shared.driver.browser_launch_kwargs for when that is needed. It is
    applied as given, so point it at a binary of the same family as
    `cfg_browser`.
    """
    from poms.shared.driver import browser_launch_kwargs

    launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
    return await launchers.get(cfg_browser, pw.chromium).launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled"],
        **browser_launch_kwargs(),
    )


# ── Can the browser even launch? ──────────────────────────────────────────────

def browser_preflight(cfg_browser: str = "chromium") -> list[str]:
    """
    What would stop launch_browser from working, checked without launching.

    This is the web domain's plan-time check (M5). It runs before a workflow
    starts, so "please run playwright install" arrives instead of a run that
    plans, validates, opens reporters and only then dies.

    Silence is not a promise that the launch will succeed — it means nothing
    *certainly* wrong was found. Every uncertain case reports nothing on
    purpose: a false "no browser" blocks a run that would have worked, which is
    a worse failure than the late one this replaces.
    """
    try:
        import playwright
    except ImportError:
        return ["playwright is not installed — pip install -r requirements.txt"]

    override = os.environ.get("BROWSER_EXECUTABLE_PATH", "").strip()
    if override and Path(override).exists():
        return []          # the escape hatch decides which binary runs; trust it

    missing = _missing_browser_build(cfg_browser, Path(playwright.__file__).parent)
    return [missing] if missing else []


def _missing_browser_build(cfg_browser: str, package_root: Path) -> str | None:
    """
    The revision Playwright insists on, and whether it is on disk.

    Playwright refuses to launch against any build but the exact revision its
    version pins — the mismatch poms.shared.driver.browser_launch_kwargs exists
    to work around. That revision is declared in the driver's own browsers.json,
    so the answer is a directory lookup rather than a launch attempt.
    """
    try:
        manifest = package_root / "driver" / "package" / "browsers.json"
        entries = json.loads(manifest.read_text(encoding="utf-8")).get("browsers", [])
    except Exception:
        return None                          # cannot tell → say nothing

    entry = next((b for b in entries if b.get("name") == cfg_browser), None)
    revision = (entry or {}).get("revision")
    if entry is None or revision is None or entry.get("revisionOverrides"):
        # revisionOverrides means the wanted revision varies by platform, and
        # resolving that here would duplicate Playwright's own logic badly.
        return None

    root = _browsers_root()
    if root is None:
        return None
    if (root / f"{cfg_browser}-{revision}").is_dir():
        return None

    present = sorted(p.name for p in root.iterdir()
                     if p.is_dir() and p.name.startswith(f"{cfg_browser}-")) \
        if root.is_dir() else []
    found = f" (found {', '.join(present)})" if present else ""
    return (
        f"{cfg_browser} build {revision} is not installed in {root}{found} — run "
        f"`playwright install {cfg_browser}`, or point BROWSER_EXECUTABLE_PATH "
        f"at a binary you already have"
    )


def _browsers_root() -> Path | None:
    """
    Where Playwright keeps its browsers, or None when that is not knowable.

    PLAYWRIGHT_BROWSERS_PATH=0 installs them beside the package in a layout
    this check does not model, so it answers None rather than guessing.
    """
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if raw == "0":
        return None
    if raw:
        return Path(raw)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "ms-playwright" if local else None
    return Path.home() / ".cache" / "ms-playwright"


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
            mod = importlib.import_module(f"stepper.sites.{site}.register")
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
