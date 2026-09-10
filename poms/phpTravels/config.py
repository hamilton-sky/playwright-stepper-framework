"""
phpTravels/config.py — Settings loader for the phpTravels POM.

Reads from (in priority order):
  1. Environment variables  (PHPTRAVELS_*)
  2. DEFAULTS below

No site-specific selectors or flow logic live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from poms.shared.config import load_config_data

_THIS_DIR = Path(__file__).resolve().parent   # poms/phpTravels/


@dataclass(frozen=True)
class Settings:
    base_url:  str
    email:     str | None
    password:  str | None
    headless:  bool
    slow_mo_ms: int


DEFAULTS: dict = {
    "base_url":   "https://phptravels.com/demo",
    "email":      None,
    "password":   None,
    "headless":   True,
    "slow_mo_ms": 0,
}

ENV_MAP: dict[str, str] = {
    "PHPTRAVELS_BASE_URL":  "base_url",
    "PHPTRAVELS_EMAIL":     "email",
    "PHPTRAVELS_PASSWORD":  "password",
    "PHPTRAVELS_HEADLESS":  "headless",
    "PHPTRAVELS_SLOW_MO":   "slow_mo_ms",
}


def load_settings(config_path: str | Path | None = None) -> Settings:
    data = load_config_data(
        DEFAULTS,
        ENV_MAP,
        config_path=config_path if config_path is not None else _THIS_DIR / "config" / "config.yaml",
        bool_fields={"headless"},
        int_fields={"slow_mo_ms"},
    )

    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        email=data.get("email") or None,
        password=data.get("password") or None,
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
    )
