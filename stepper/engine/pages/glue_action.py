"""
stepper/stepper/pages/glue_action.py — Base class for all glue-layer actions.

GlueAction sits between the generic ActionStrategy (engine) and the concrete
site-specific action classes (OLEnsureLoginAction, SDLoginAction, …).

It establishes the interface for "executing a step against a POM":

  1. _build_pom(pom_cls, *args, page, resolver, **kwargs)
       Constructs a POM with page= and resolver= always injected.
       Using this instead of calling the POM constructor directly makes
       it structurally impossible to forget the resolver= argument.

  2. _driver(page) -> PlaywrightDriver
       Wraps the Playwright page in the shared driver adapter.
       Every _execute starts with this — one call, no import boilerplate.

Usage in a glue _execute:

    async def _execute(self, page, step, resolver, context):
        from poms.mysite.config import load_settings
        from poms.mysite.pages.some_page import SomePage

        settings = load_settings()
        driver   = self._driver(page)
        pom      = self._build_pom(SomePage, driver, settings.base_url,
                                   page=page, resolver=resolver)
        ...

All site action inner classes (OLEnsureLoginAction, SDLoginAction, …) must
subclass GlueAction, not ActionStrategy directly.
"""

from __future__ import annotations

from typing import TypeVar

from engine.interfaces import ActionStrategy

T = TypeVar("T")


class GlueAction(ActionStrategy):

    async def execute(self, page, step, resolver, context, behaviour):
        # The runner passes the 'official' behaviour instance here
        return await self._execute(page, step, resolver, context, behaviour)

    def _build_pom(self, pom_cls, *args, page, resolver, behaviour, **kwargs):
        """
        Updated to make behaviour a mandatory argument.
        """
        return pom_cls(*args, page=page, resolver=resolver, 
                       behaviour=behaviour, **kwargs)

    @staticmethod
    def _driver(page):
        """
        Wrap the Playwright page in PlaywrightDriver.

        Imported lazily to keep the glue layer free of top-level poms imports.
        """
        from poms.shared.driver import PlaywrightDriver
        return PlaywrightDriver(page)
