"""
sites/_noop/register.py — Registers the noop domain and its actions.

Discovered by bootstrap.infra.register_all_sites, which globs
``sites/*/register.py`` and needed no change to find this one — which was the
claim docs/universal-runner-plan.md §2 made about adding a domain, and this is
what tests it.

Registering the Domain here rather than in bootstrap/session.py is the point:
a domain declares itself from its own folder, next to the actions that use it.

The Domain is built once, at module scope, on purpose. register() is called
more than once per process — `main.py actions` builds two registries, and
prepare_run builds its own — and register_domain refuses to replace a domain
with a *different* one under the same name. A Domain built inside register()
would be a new object with a new session lambda on every call, so the second
call would trip that guard. One module-level constant is re-registered
identically and passes.
"""

from __future__ import annotations

from stepper.bootstrap.session import Domain, no_hooks, no_shared, register_domain
from stepper.engine.session import NullSession


def _noop_session(cfg=None, settings=None, test_reporter=None, *, shared=None):
    """
    NullSession needs no run configuration.

    The composition root passes cfg, settings, test_reporter and shared to
    every domain's session factory; this one accepts them and ignores them,
    which is what "a domain with nothing to open" looks like in practice.
    """
    return NullSession("noop")


NOOP_DOMAIN = Domain(
    name="noop",
    session=_noop_session,
    hooks=no_hooks,
    shared=no_shared,
)


def register(registry, screenshots_dir=None) -> None:
    from stepper.sites._noop.pages.noop_page import NoopPage

    NoopPage.register(registry)
    register_domain(NOOP_DOMAIN)
