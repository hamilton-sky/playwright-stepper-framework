"""
saucedemo/config.py — Settings loader for the SauceDemo POM.

Reads from (in priority order):
  1. Environment variables  (SAUCEDEMO_*)
  2. poms/saucedemo/config/config.yaml  (optional)
  3. DEFAULTS below

No OpenLibrary-specific logic lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_THIS_DIR = Path(__file__).resolve().parent   # poms/saucedemo/


@dataclass(frozen=True)
class Settings:
    base_url:            str
    headless:            bool
    slow_mo_ms:          int
    browser:             str
    username:            str | None
    password:            str | None
    screenshots_dir:     Path
    logs_dir:            Path
    performance_output:  Path


DEFAULTS: dict = {
    "base_url":           "https://www.saucedemo.com",
    "headless":           True,
    "slow_mo_ms":         0,
    "browser":            "chromium",
    "screenshots_dir":    "artifacts/saucedemo/screenshots",
    "logs_dir":           "artifacts/saucedemo/logs",
    "performance_output": "artifacts/saucedemo/performance.json",
}

ENV_MAP: dict[str, str] = {
    "SAUCEDEMO_BASE_URL":    "base_url",
    "SAUCEDEMO_HEADLESS":    "headless",
    "SAUCEDEMO_SLOW_MO_MS":  "slow_mo_ms",
    "SAUCEDEMO_BROWSER":     "browser",
    "SAUCEDEMO_USERNAME":    "username",
    "SAUCEDEMO_PASSWORD":    "password",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def load_settings(config_path: str | Path | None = None) -> Settings:
    if config_path is None:
        config_path = _THIS_DIR / "config" / "config.yaml"

    data = dict(DEFAULTS)

    path = Path(config_path)
    if path.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config.yaml")
        file_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(file_data, dict):
            raise ValueError("config.yaml must contain a top-level mapping")
        data.update(file_data)

    for env_key, field in ENV_MAP.items():
        if env_key in os.environ:
            raw = os.environ[env_key]
            if field == "headless":
                data[field] = _parse_bool(raw)
            elif field == "slow_mo_ms":
                data[field] = int(raw)
            else:
                data[field] = raw

    def _abs(p: str | Path) -> Path:
        resolved = Path(p)
        return resolved if resolved.is_absolute() else _THIS_DIR / resolved

    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
        browser=str(data["browser"]),
        username=data.get("username") or None,
        password=data.get("password") or None,
        screenshots_dir=_abs(data["screenshots_dir"]),
        logs_dir=_abs(data["logs_dir"]),
        performance_output=_abs(data["performance_output"]),
    )
