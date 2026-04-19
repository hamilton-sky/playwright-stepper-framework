from __future__ import annotations
from pathlib import Path
from typing import NamedTuple


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


def load_settings_safe() -> RunSettings:
    from poms.openLibrary.config import load_settings, validate_ai_config
    try:
        settings = load_settings()
        validate_ai_config(settings)
        return RunSettings(
            use_visual_ai=settings.use_visual_ai,
            slow_mo=settings.slow_mo_ms,
            browser=settings.browser,
            storage_state_path=settings.storage_state_path,
        )
    except Exception:
        return RunSettings(use_visual_ai=False, slow_mo=300, browser="chromium", storage_state_path=None)
