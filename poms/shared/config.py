"""
shared/config.py — the settings-loading algorithm every site shares.

Each site's ``config.py`` used to carry its own copy of the same three things:
a byte-identical ``_parse_bool``, a DEFAULTS → config.yaml → environment merge,
and a helper to resolve relative paths against the package directory. Three
copies, drifting independently — phpTravels' had already lost YAML support.

What is *not* shared, deliberately, is the ``Settings`` dataclass. Field sets
genuinely differ (OpenLibrary carries delays, shelf_paths and login_url;
phpTravels has five fields in total), and collapsing them into one wide
optional-everything class would trade real duplication for a worse problem.
Sites share the algorithm and keep their own schema.

Typical use::

    data = load_config_data(
        DEFAULTS, ENV_MAP,
        config_path=_THIS_DIR / "config" / "config.yaml",
        bool_fields={"headless"},
        int_fields={"slow_mo_ms"},
    )
    return Settings(base_url=str(data["base_url"]).rstrip("/"), ...)
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is declared, but stay importable
    yaml = None


_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def parse_bool(value: str) -> bool:
    """Parse an environment variable's string into a bool."""
    return value.strip().lower() in _TRUTHY


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    """Absolute paths as given; relative ones resolved against the site package."""
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def load_config_data(
    defaults: Mapping[str, Any],
    env_map: Mapping[str, str],
    config_path: str | Path | None = None,
    bool_fields: Iterable[str] = (),
    int_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """
    Merge a site's settings from its three sources, lowest precedence first.

    1. ``defaults``
    2. ``config_path`` — a YAML mapping, when the file exists
    3. environment variables named by ``env_map`` (``ENV_NAME -> field``)

    ``bool_fields`` and ``int_fields`` name the fields whose environment values
    need coercing; everything else is left as the string the environment gave.

    Args:
        defaults:     Field → default value.
        env_map:      Environment variable name → field name.
        config_path:  Optional YAML file. Missing is fine; malformed is not.
        bool_fields:  Fields to run through ``parse_bool``.
        int_fields:   Fields to run through ``int``.

    Returns:
        The merged mapping. The caller builds its own Settings from it, so this
        never has to know which fields a given site actually has.

    Raises:
        RuntimeError: config.yaml exists but PyYAML is not installed.
        ValueError:   config.yaml does not contain a top-level mapping, or an
                      int field holds something that is not an integer.
    """
    data: dict[str, Any] = dict(defaults)

    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            if yaml is None:
                raise RuntimeError(f"PyYAML is required to read {path}")
            file_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(file_data, dict):
                raise ValueError(f"{path} must contain a top-level mapping")
            data.update(file_data)

    bools, ints = set(bool_fields), set(int_fields)
    for env_key, field in env_map.items():
        if env_key not in os.environ:
            continue
        raw = os.environ[env_key]
        if field in bools:
            data[field] = parse_bool(raw)
        elif field in ints:
            try:
                data[field] = int(raw)
            except ValueError as exc:
                # Silently falling back to the default would hide a typo in an
                # environment variable behind timings that look merely odd.
                raise ValueError(
                    f"{env_key}={raw!r} is not an integer (sets {field!r})"
                ) from exc
        else:
            data[field] = raw

    return data
