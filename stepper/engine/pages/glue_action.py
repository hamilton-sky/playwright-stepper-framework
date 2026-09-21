"""
stepper/stepper/pages/glue_action.py — Base class for all glue-layer actions.

GlueAction sits between the generic ActionStrategy (engine) and the concrete
site-specific action classes (OLEnsureLoginAction, SDLoginAction, …).

It establishes the interface for "executing a step against a POM":

  1. _build_pom(pom_cls, *args, page, resolver, behaviour, **kwargs)
       Constructs a POM with page=, resolver= and behaviour= always injected.
       Using this instead of calling the POM constructor directly makes
       it structurally impossible to forget the resolver= argument.

  2. _driver(page) -> IBrowserDriver
       Wraps the session in the driver adapter the run is configured with.
       Every _execute starts with this — one call, no import boilerplate.
       The concrete adapter is PlaywrightDriver unless something swapped it;
       see set_driver_factory below.

Usage in a glue _execute:

    async def _execute(self, page, step, resolver, context, behaviour=None):
        from poms.mysite.config import load_settings
        from poms.mysite.pages.some_page import SomePage

        settings = load_settings()
        driver   = self._driver(page)
        pom      = self._build_pom(SomePage, driver, settings.base_url,
                                   page=page, resolver=resolver,
                                   behaviour=behaviour)
        ...

All site action inner classes (OLEnsureLoginAction, SDLoginAction, …) must
subclass GlueAction, not ActionStrategy directly, and implement _execute with
the signature (self, page, step, resolver, context, behaviour=None).

That rule is about POMs, so it is a web rule. A domain with no selectors has
no POM layer and its actions subclass ActionStrategy directly — see
stepper/sites/_noop/ and docs/universal-runner-plan.md §4.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from stepper.engine.interfaces import ActionStrategy

T = TypeVar("T")


def _playwright_driver(page):
    """
    The default adapter: Playwright's Page behind IBrowserDriver.

    Imported inside the function so that importing this module costs no
    browser — poms/shared/driver.py is the one file that knows Playwright
    exists, and a run with no browser in it should not load it.
    """
    from poms.shared.driver import PlaywrightDriver
    return PlaywrightDriver(page)


_driver_factory: Callable[[object], object] = _playwright_driver


def set_driver_factory(factory: Callable[[object], object]):
    """
    Swap the driver adapter every glue action builds. Returns the previous one,
    so a caller can restore it.

    ARCHITECTURE.md has always claimed "swap the browser adapter → touches
    existing code? No". Until this existed it was not true: GlueAction._driver
    imported PlaywrightDriver and constructed it by name, so swapping the
    adapter meant editing the base class every glue action inherits from.

        previous = set_driver_factory(lambda page: MyDriver(page))
        ...
        set_driver_factory(previous)

    For a swap that should apply to one action rather than the whole process,
    set the `driver_factory` class attribute on it instead.
    """
    global _driver_factory
    previous, _driver_factory = _driver_factory, factory
    return previous


def reset_driver_factory():
    """Restore the Playwright default. Mostly for tests."""
    return set_driver_factory(_playwright_driver)


def get_driver_factory() -> Callable[[object], object]:
    """The factory currently in force."""
    return _driver_factory


class GlueAction(ActionStrategy):
    """
    Base for every site-specific glue action.

    Deliberately does NOT override execute(): glue actions run through the same
    ActionStrategy template method as engine actions, so pre_execute /
    post_execute hooks and ExecutionContext defaulting apply to them too.
    The template method forwards `behaviour` into _execute for us.
    """

    def _build_pom(self, pom_cls, *args, page, resolver, behaviour, **kwargs):
        """
        Construct a POM with page=, resolver= and behaviour= always injected.

        behaviour is keyword-mandatory: forgetting it is a TypeError at the call
        site rather than a silently un-humanised POM. Pass the behaviour handed
        to _execute — it may be None when the action runs outside a StepRunner.
        """
        return pom_cls(*args, page=page, resolver=resolver,
                       behaviour=behaviour, **kwargs)

    #: Per-action override. None means "whatever set_driver_factory last set",
    #: which is PlaywrightDriver unless something changed it.
    driver_factory: Callable[[object], object] | None = None

    def _driver(self, page):
        """
        Wrap the session in the driver adapter this run is using.

        Resolved per call rather than captured at construction: actions are
        registered once at startup and live for the whole process, so a factory
        read at __init__ would pin the adapter chosen before any run began.
        """
        factory = self.driver_factory or get_driver_factory()
        return factory(page)
