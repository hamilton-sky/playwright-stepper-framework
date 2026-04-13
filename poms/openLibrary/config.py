from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from poms.shared.interfaces import Delays


@dataclass(frozen=True)
class Settings:
    base_url: str
    headless: bool
    slow_mo_ms: int
    browser: str
    username: str | None
    password: str | None
    screenshots_dir: Path
    storage_state_path: Path
    performance_output: Path
    report_output: Path
    logs_dir: Path
    delays: Delays
    use_visual_ai: bool
    login_url: str
    max_login_attempts: int
    shelf_paths: tuple[str, ...]


DEFAULTS = {
    "base_url": "https://openlibrary.org",
    "headless": True,
    "slow_mo_ms": 0,
    "browser": "chromium",
    "screenshots_dir": "artifacts/screenshots",
    "storage_state_path": "artifacts/storage_state.json",
    "performance_output": "artifacts/performance.json",
    "report_output": "artifacts/exam_report.json",
    "logs_dir": "artifacts/logs",
    "use_visual_ai": False,
    "login_url": "https://openlibrary.org/account/login",
    "max_login_attempts": 3,
    "shelf_paths": ["/account/books/want-to-read", "/account/books/already-read"],
}


ENV_MAP = {
    "OPENLIBRARY_BASE_URL": "base_url",
    "OPENLIBRARY_HEADLESS": "headless",
    "OPENLIBRARY_SLOW_MO_MS": "slow_mo_ms",
    "OPENLIBRARY_BROWSER": "browser",
    "OPENLIBRARY_USERNAME": "username",
    "OPENLIBRARY_PASSWORD": "password",
    "OPENLIBRARY_SCREENSHOTS_DIR": "screenshots_dir",
    "OPENLIBRARY_STORAGE_STATE": "storage_state_path",
    "OPENLIBRARY_PERF_OUTPUT": "performance_output",
    "OPENLIBRARY_USE_VISUAL_AI": "use_visual_ai",
}


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


# Find openlibrary config file location (in parent openlibrary module)
_SHARED_POMS_DIR = Path(__file__).resolve().parent
_OPENLIBRARY_DIR = _SHARED_POMS_DIR.parent


def load_settings(
    config_path: str | Path | None = None,
) -> Settings:
    if config_path is None:
        config_path = _OPENLIBRARY_DIR / "config" / "config.yaml"
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
            if field in {"headless", "use_visual_ai"}:
                data[field] = _parse_bool(raw)
            elif field in {"slow_mo_ms"}:
                data[field] = int(raw)
            else:
                data[field] = raw

    # Load delays configuration
    delays_config = data.get("delays", {})
    delays = Delays(
        page_load_wait_ms=int(delays_config.get("page_load_wait_ms", 1000)),
        between_actions_ms=int(delays_config.get("between_actions_ms", 300)),
        between_pagination_ms=int(delays_config.get("between_pagination_ms", 1000)),
        post_login_wait_ms=int(delays_config.get("post_login_wait_ms", 1000)),
        retry_backoff_ms=int(delays_config.get("retry_backoff_ms", 2000)),
        search_submit_delay_ms=int(delays_config.get("search_submit_delay_ms", 500)),
        max_search_pages=int(delays_config.get("max_search_pages", 5)),
    )

    raw_shelf_paths = data.get("shelf_paths", DEFAULTS["shelf_paths"])
    shelf_paths = tuple(str(p) for p in raw_shelf_paths)

    def _abs(p: str | Path) -> Path:
        """Resolve relative paths against the openlibrary directory, not CWD."""
        resolved = Path(p)
        return resolved if resolved.is_absolute() else _OPENLIBRARY_DIR / resolved

    return Settings(
        base_url=str(data["base_url"]),
        headless=bool(data["headless"]),
        slow_mo_ms=int(data["slow_mo_ms"]),
        browser=str(data["browser"]),
        username=data.get("username") or None,
        password=data.get("password") or None,
        screenshots_dir=_abs(data["screenshots_dir"]),
        storage_state_path=_abs(data["storage_state_path"]),
        performance_output=_abs(data["performance_output"]),
        report_output=_abs(data["report_output"]),
        logs_dir=_abs(data.get("logs_dir", DEFAULTS["logs_dir"])),
        delays=delays,
        use_visual_ai=bool(data.get("use_visual_ai", False)),
        login_url=str(data.get("login_url", DEFAULTS["login_url"])),
        max_login_attempts=int(data.get("max_login_attempts", DEFAULTS["max_login_attempts"])),
        shelf_paths=shelf_paths,
    )


def load_test_data(path: str | Path | None = None) -> list[dict]:
    if path is None:
        path = _SHARED_POMS_DIR / "data" / "testdata.json"
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Test data file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("testdata.json must contain a list of cases")
    return data
