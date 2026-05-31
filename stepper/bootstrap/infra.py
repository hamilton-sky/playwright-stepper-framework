from __future__ import annotations
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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


async def launch_browser(pw, cfg_browser: str, headless: bool, slow_mo: int,
                         browser_type: str = "chromium", cdp_port: int | None = None):
    if browser_type == "electron":
        from engine.browser.electron_launcher import launch_electron_cdp
        from sites.pathly.electron_config import DEFAULT_CDP_PORT
        return await launch_electron_cdp(port=cdp_port or DEFAULT_CDP_PORT)
    launchers = {"chromium": pw.chromium, "firefox": pw.firefox, "webkit": pw.webkit}
    return await launchers.get(cfg_browser, pw.chromium).launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled"],
    )


def register_all_sites(registry, stepper_root: Path, screenshots_dir=None) -> None:
    for reg_path in sorted((stepper_root / "sites").glob("*/register.py")):
        module_name = f"sites.{reg_path.parent.name}.register"
        try:
            mod = importlib.import_module(module_name)
            mod.register(registry, screenshots_dir=screenshots_dir)
        except Exception as exc:
            logger.warning(f"Could not register site {reg_path.parent.name}: {exc}")
