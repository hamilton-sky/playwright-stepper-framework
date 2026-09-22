"""
sites/db/session.py — The db domain's SessionAdapter, and its preflight.

This is the first session in the tree that is not a browser and is not a
placeholder, which is the whole point of M6: `_noop` has nothing to open, so it
could never find out whether the session contract was quietly shaped around
Playwright. A sqlite3 connection has real lifecycle — it holds a transaction —
so it is the first thing to actually test that contract.

The one decision worth spelling out is what `close()` does with uncommitted
work. It **commits**, and does not roll back:

    A workflow is a script someone wrote to make things happen. A run that
    inserted rows and then discarded them at teardown would report every step
    passed while leaving nothing behind — silence instead of a failure, which
    is the exact shape of bug the universal-runner work existed to remove.

`db_execute` commits per step anyway, so the commit here only covers a session
closed between a write and a step boundary. A workflow that wants rollback
semantics should say so in SQL; the adapter does not guess.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class SqliteSession:
    """
    Opens a sqlite3 connection and hands it to every db action.

    `open()` returns the Connection itself, mirroring WebSession returning a
    Page: the object actions receive is the domain's natural handle, and the
    runner never inspects either one.
    """

    domain = "db"

    def __init__(self, cfg=None, settings=None, test_reporter=None, *, shared=None):
        # `settings` is the *run's* settings — the composition root has one per
        # run and hands the same one to every domain's session factory. The db
        # domain reads its own rather than expecting fields in that one.
        from stepper.sites.db.config import load_settings

        self._settings = load_settings()
        self._conn: sqlite3.Connection | None = None

    async def open(self) -> sqlite3.Connection:
        path = self._settings.db_path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), timeout=self._settings.timeout_s)
        self._conn.row_factory = sqlite3.Row
        logger.info(f"db: opened {path}")
        return self._conn

    async def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.commit()
        finally:
            self._conn.close()
            self._conn = None


def db_preflight(cfg=None, settings=None) -> list[str]:
    """
    What would stop a connection opening, checked before anything opens (M5).

    sqlite3 is in the standard library, so nothing can be *missing* — but the
    file has to be creatable, and a directory that is absent-and-uncreatable or
    present-and-read-only is a certain failure worth naming at plan time rather
    than at the first db step.

    Same rule as the browser's preflight: report only what is certain. An
    existing file that happens to be corrupt is not detectable without opening
    it, so it is not this function's business. `os.access` is also generous to
    root, which means this under-reports when the suite runs as root — that is
    the designed direction to be wrong in, for the reason browser_preflight
    gives: a false "not ready" blocks a run that would have worked.
    """
    from stepper.sites.db.config import load_settings

    try:
        path = load_settings().db_path
    except Exception as exc:
        return [f"db settings could not be loaded: {type(exc).__name__}: {exc}"]

    if path == ":memory:":
        return []

    target = Path(path)
    if target.exists():
        return ([] if os.access(target, os.W_OK)
                else [f"{target} exists but is not writable"])

    parent = target.parent
    if parent.exists():
        if not parent.is_dir():
            return [f"{parent} is not a directory, so {target.name} "
                    f"cannot be created inside it"]
        return ([] if os.access(parent, os.W_OK)
                else [f"{parent} is not writable, so {target.name} cannot be created"])

    # The directory does not exist yet. open() creates it, so the question is
    # whether the nearest ancestor that *does* exist allows that.
    existing = next((p for p in parent.parents if p.exists()), None)
    if existing is not None and not os.access(existing, os.W_OK):
        return [f"{parent} does not exist and {existing} is not writable, "
                f"so it cannot be created"]
    return []
