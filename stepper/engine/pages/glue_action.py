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

from typing import TypeVar, Type

from engine.interfaces import ActionStrategy

T = TypeVar("T")


class GlueAction(ActionStrategy):
    """
    Base class for all site-specific (glue-layer) actions.

    Provides two construction helpers that encode the resolver-injection
    contract so it cannot be accidentally omitted:

      _build_pom  — construct any POM with page= and resolver= enforced
      _driver     — wrap a Playwright page in PlaywrightDriver
    """

    @staticmethod
    def _build_pom(pom_cls: Type[T], *args, page, resolver, **kwargs) -> T:
        """
        Construct a POM instance with resolver injection enforced.

        Calling this instead of the POM constructor directly makes it
        impossible to forget page= or resolver= — both are keyword-only
        and required by this signature.

        Example:
            pom = self._build_pom(LoginPage, driver, settings.base_url,
                                  settings.delays, page=page, resolver=resolver)
        """
        return pom_cls(*args, page=page, resolver=resolver, **kwargs)

    @staticmethod
    def _driver(page):
        """
        Wrap the Playwright page in PlaywrightDriver.

        Imported lazily to keep the glue layer free of top-level poms imports.
        """
        from poms.shared.driver import PlaywrightDriver
        return PlaywrightDriver(page)
