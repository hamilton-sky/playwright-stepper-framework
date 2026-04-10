from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from interfaces import Delays


@dataclass(frozen=True)
class Settings:
    base_url: str
    headless: bool
    slow_mo_ms: int
    browser: str
    screenshots_dir: Path
    storage_state_path: Path
    delays: Delays


DEFAULTS = {
    "base_url": "https://www.goodreads.com",
    "headless": True,
    "slow_mo_ms": 200,
    "browser": "chromium",
    "screenshots_dir": "artifacts/screenshots",
    "storage_state_path": "artifacts/storage_state.json",
}


ENV_MAP = {
    "GOODREADS_BASE_URL": "base_url",
    "GOODREADS_HEADLESS": "headless",
    "GOODREADS_SLOW_MO_MS": "slow_mo_ms",
    "GOODREADS_BROWSER": "browser",
    "GOODREADS_SCREENSHOTS_DIR": "screenshots_dir",
    "GOODREADS_STORAGE_STATE": "storage_state_path",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def load_settings(config_path: str | Path = "goodreads/config/config.yaml") -> Settings:
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
            if field in {"headless"}:
                data[field] = _parse_bool(raw)
            elif field in {"slow_mo_ms"}:
                data[field] = int(raw)
            else:
                data[field] = raw

    delays_config = data.get("delays", {})
    delays = Delays(
        page_load_wait_ms=int(delays_config.get("page_load_wait_ms", 1000)),
        between_actions_ms=int(delays_config.get("between_actions_ms", 300)),
        between_pagination_ms=int(delays_config.get("between_pagination_ms", 1000)),
        post_login_wait_ms=int(delays_config.get("post_login_wait_ms", 1000)),
        retry_backoff_ms=int(delays_config.get("retry_backoff_ms", 2000)),
        search_submit_delay_ms=int(delays_config.get("search_submit_delay_ms", 500)),
    )

    return Settings(
        base_url=str(data["base_url"]),
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
        browser=str(data["browser"]),
        screenshots_dir=Path(data["screenshots_dir"]),
        storage_state_path=Path(data["storage_state_path"]),
        delays=delays,
    )
