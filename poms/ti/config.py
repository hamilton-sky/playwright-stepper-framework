"""ti/config.py — Settings loader for the-internet POM."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

_THIS_DIR = Path(__file__).resolve().parent


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
    if config_path is None:
        config_path = _THIS_DIR / "config" / "config.yaml"

    data = dict(DEFAULTS)

    path = Path(config_path)
    if path.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config.yaml")
        file_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(file_data, dict):
            data.update(file_data)

    for env_key, field in ENV_MAP.items():
        if env_key in os.environ:
            data[field] = os.environ[env_key]

    return Settings(
        base_url=str(data["base_url"]).rstrip("/"),
        username=data.get("username") or None,
        password=data.get("password") or None,
    )
