"""
phpTravels/config.py — Settings loader for the phpTravels POM.

Reads from (in priority order):
  1. Environment variables  (PHPTRAVELS_*)
  2. DEFAULTS below

No site-specific selectors or flow logic live here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def load_settings() -> Settings:
    data = dict(DEFAULTS)

    for env_key, field in ENV_MAP.items():
        if env_key in os.environ:
            raw = os.environ[env_key]
            if field == "headless":
                data[field] = _parse_bool(raw)
            elif field == "slow_mo_ms":
                data[field] = int(raw)
            else:
                data[field] = raw

    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        email=data.get("email") or None,
        password=data.get("password") or None,
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
    )
