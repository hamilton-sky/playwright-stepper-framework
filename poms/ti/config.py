"""
ti/config.py — Settings loader for the-internet POM.

The DEFAULTS → config.yaml → environment merge is *not* written here:
`poms/shared/config.py` owns that algorithm, and its docstring records what
three private copies cost last time ("Three copies, drifting independently —
phpTravels' had already lost YAML support"). This file supplies only what is
genuinely this site's: its fields, its defaults and its environment names.

Credentials live in config/config.yaml, the way SauceDemo's do, because
the-internet publishes them on its own login page — they gate nothing. Anything
real belongs in TI_USER / TI_PASS instead, which take precedence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from poms.shared.config import load_config_data

_THIS_DIR = Path(__file__).resolve().parent          # poms/ti/


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str | None
    password: str | None


DEFAULTS: dict = {
    "base_url": "https://the-internet.herokuapp.com",
}

ENV_MAP: dict[str, str] = {
    "TI_BASE_URL": "base_url",
    "TI_USER":     "username",
    "TI_PASS":     "password",
}


def load_settings(config_path: str | Path | None = None) -> Settings:
    data = load_config_data(
        DEFAULTS,
        ENV_MAP,
        config_path=config_path if config_path is not None
        else _THIS_DIR / "config" / "config.yaml",
    )
    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        username=data.get("username") or None,
        password=data.get("password") or None,
    )
