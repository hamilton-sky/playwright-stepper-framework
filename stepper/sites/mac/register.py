"""
sites/mac/register.py — Registers the mac domain and its actions.

Discovered by bootstrap.infra.register_all_sites, which globs
``sites/*/register.py`` — no change needed there, same as sites/db/ and
sites/_noop/ proved.

The Domain is a module-level constant for the reason sites/_noop/register.py
explains: register() runs more than once per process, and register_domain
refuses to replace a domain with a *different* object under the same name.
"""

from __future__ import annotations

from stepper.bootstrap.session import (
    Domain, no_hooks, no_shared, register_domain,
)
from stepper.sites.mac.session import MacSession, mac_preflight

MAC_DOMAIN = Domain(
    name="mac",
    session=MacSession,
    hooks=no_hooks,            # nothing to screenshot, nothing to wait for
    shared=no_shared,          # one handle per run; nothing to share
    preflight=mac_preflight,   # macOS + osascript, checked before anything runs
)


def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.mac.pages.mac_page import MacPage

    MacPage.register(registry)
    register_domain(MAC_DOMAIN)
