"""
healing_cache.py — Persistent per-site JSON cache for healed element cfgs.

Keyed by a 16-char SHA-256 of (action, description, element).
On cache HIT the cascade and AI call are skipped entirely.
"""

from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class HealCache:
    def __init__(self, cache_path: Path):
        self._path = cache_path
        self._data: dict[str, dict] = {}
        if cache_path.exists():
            try:
                self._data = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"[HealCache] corrupt cache at {cache_path} — starting empty ({exc})")

    @staticmethod
    def make_key(step) -> str:
        raw = (
            f"{step.action}"
            f"|{step.description or ''}"
            f"|{json.dumps(step.element or {}, sort_keys=True)}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, step) -> dict | None:
        return self._data.get(self.make_key(step))

    def put(self, step, healed_cfg: dict) -> None:
        self._data[self.make_key(step)] = healed_cfg
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"[HealCache] wrote entry for '{step.action}'")
        except Exception as exc:
            logger.warning(f"[HealCache] could not write cache: {exc}")
