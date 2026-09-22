"""
sites/db/config.py — Where the SQLite file lives.

Deliberately *not* under poms/. A POM is the single home of a page's selectors;
a database has no pages, so a `poms/db/` would be a folder named after a layer
it is not in. The domain declares itself from its own folder under
stepper/sites/ — the same thing sites/_noop/register.py says about its Domain —
and its configuration belongs beside it.

The loader itself is shared with every site: `poms.shared.config` holds the
DEFAULTS → config.yaml → environment merge, and a fourth private copy of that
is exactly the drift its docstring describes. Importing it here is the legal
direction (stepper → poms, never the reverse) and it is browser-free: it pulls
in `poms`, `poms.shared` and `poms.shared.config` and nothing else, which is
what keeps a db-only run from loading Playwright.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from poms.shared.config import load_config_data, resolve_path

_THIS_DIR = Path(__file__).resolve().parent          # stepper/sites/db/


@dataclass(frozen=True)
class Settings:
    #: The SQLite file. ":memory:" is accepted but close to useless here — each
    #: connection gets its own empty database, so nothing survives a step.
    db_path: Path | str
    #: Seconds sqlite3 waits on a locked database before raising.
    timeout_s: int


DEFAULTS: dict = {
    "db_path":   "artifacts/stepper.db",
    "timeout_s": 5,
}

ENV_MAP: dict[str, str] = {
    "STEPPER_DB_PATH":    "db_path",
    "STEPPER_DB_TIMEOUT": "timeout_s",
}


def load_settings(config_path: str | Path | None = None) -> Settings:
    data = load_config_data(
        DEFAULTS,
        ENV_MAP,
        config_path=config_path if config_path is not None
        else _THIS_DIR / "config" / "config.yaml",
        int_fields={"timeout_s"},
    )
    raw = data["db_path"]
    return Settings(
        db_path=raw if raw == ":memory:" else resolve_path(raw, _THIS_DIR),
        timeout_s=int(data["timeout_s"]),
    )
