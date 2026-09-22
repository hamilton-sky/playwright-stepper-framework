"""
sites/db/register.py — Registers the db domain and its actions.

The second real domain in the tree, and the first non-browser one with anything
to open. `_noop` proved the runner needs no browser; this proves the *domain*
abstraction is not browser-shaped, which is a different claim and the one M1–M5
could not test on their own.

Everything here is declared from this folder — session, preflight, conditions,
actions, workflows — and bootstrap.infra.register_all_sites finds it by the
same `sites/*/register.py` glob that finds saucedemo. No file outside this
directory names the db domain.

The Domain is a module-level constant for the reason sites/_noop/register.py
explains: register() runs more than once per process, and register_domain
refuses to replace a domain with a *different* object under the same name.
"""

from __future__ import annotations

from stepper.bootstrap.session import Domain, no_hooks, no_shared, register_domain
from stepper.sites.db.conditions import db_conditions
from stepper.sites.db.session import SqliteSession, db_preflight

DB_DOMAIN = Domain(
    name="db",
    session=SqliteSession,
    hooks=no_hooks,            # nothing to screenshot, nothing to wait for
    shared=no_shared,          # one connection per run; no cross-run handle
    conditions=db_conditions,
    preflight=db_preflight,
)


def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.db.pages.db_page import DbPage

    DbPage.register(registry)
    register_domain(DB_DOMAIN)
