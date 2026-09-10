from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import NamedTuple

from poms.shared.diagnostics import log_swallowed

logger = logging.getLogger(__name__)

_POMS_DIR = Path(__file__).resolve().parent.parent.parent / "poms"

#: Fallbacks when a site has no config at all, or its config could not be read.
_FALLBACK = {"use_visual_ai": False, "slow_mo": 0, "browser": "chromium"}

#: POM packages that are not sites. `poms/shared/config.py` holds the loading
#: algorithm every site uses, not a site's settings — and `RunConfig.site` is
#: literally "shared" for a --task run, so without this the two would collide.
_NOT_A_SITE = frozenset({"shared"})


class RunSettings(NamedTuple):
    use_visual_ai: bool
    slow_mo: int
    browser: str
    storage_state_path: str | None


def load_env() -> None:
    from dotenv import load_dotenv
    here = Path(__file__).resolve().parent.parent  # stepper/
    for candidate in (here.parent / ".env", here / ".env"):
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            break


def site_config_module(site: str) -> str | None:
    """
    Import path of a site's config module, or None when it has none.

    The stepper site directory and the POM package disagree on case
    (``stepper/sites/openlibrary`` ↔ ``poms/openLibrary``), so the match is
    case-insensitive. Discovered rather than hardcoded, so a new site's config
    is picked up by adding the directory — the same way its actions are.
    """
    if not site:
        return None
    wanted = site.lower()
    for candidate in sorted(_POMS_DIR.glob("*/config.py")):
        package = candidate.parent.name
        if package in _NOT_A_SITE:
            continue
        if package.lower() == wanted:
            return f"poms.{package}.config"
    return None


def load_settings_safe(site: str | None = None) -> RunSettings:
    """
    Engine-level settings for the site being run.

    This used to import ``poms.openLibrary.config`` unconditionally, so a
    SauceDemo run took its browser and slow-mo from OpenLibrary's config and
    ``SAUCEDEMO_BROWSER`` did nothing at all — a documented environment
    variable that silently had no effect, left over from when OpenLibrary was
    the only site.

    Falls back to conservative defaults when the site has no config module or
    its config cannot be read. The fallback is logged rather than swallowed:
    the previous version returned ``slow_mo=300`` from a bare ``except``, so a
    broken config quietly changed a run's timing.
    """
    module_name = site_config_module(site) if site else None

    if module_name is None:
        if site and site != "shared":
            logger.debug("No config module for site %r — using engine defaults", site)
        return RunSettings(**_FALLBACK, storage_state_path=None)

    try:
        module = importlib.import_module(module_name)
        settings = module.load_settings()

        validate = getattr(module, "validate_ai_config", None)
        if validate is not None:
            validate(settings)

        return RunSettings(
            # Not every site declares every field — phpTravels has no browser
            # setting, and only OpenLibrary has visual AI or a saved session.
            use_visual_ai=bool(getattr(settings, "use_visual_ai", _FALLBACK["use_visual_ai"])),
            slow_mo=int(getattr(settings, "slow_mo_ms", _FALLBACK["slow_mo"])),
            browser=str(getattr(settings, "browser", _FALLBACK["browser"])),
            storage_state_path=getattr(settings, "storage_state_path", None),
        )
    except Exception as exc:
        log_swallowed(f"load_settings_safe[{site}]", exc, logger)
        logger.warning(
            "Could not load settings for site %r from %s (%s: %s) — "
            "falling back to browser=%s, slow_mo=%s.",
            site, module_name, type(exc).__name__, exc,
            _FALLBACK["browser"], _FALLBACK["slow_mo"],
        )
        return RunSettings(**_FALLBACK, storage_state_path=None)
