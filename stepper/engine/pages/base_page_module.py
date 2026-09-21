"""
pages/base_page_module.py — PageModule Abstract Base Class.

Pattern: Strategy + Template Method
  Each PageModule owns one page of one site:
    - Selector constants (ALL_CAPS class attributes — convention)
    - Domain ActionStrategy subclasses (nested classes)
    - register() — plugs actions into the shared ActionRegistry

OCP: New site = new folder + new file. Zero changes to existing code.
DIP: main.py calls register(); everything else stays on interfaces.
"""

from __future__ import annotations
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PageModule(ABC):
    """
    Abstract base for all page modules.

    Each concrete subclass represents one page of one site.

    Contract:
      - site   : short prefix string, e.g. "ol", "gr", "wiki"
      - domain : which session this page's actions act on. Defaults to "web".
      - register(): plugs this page's domain actions into the ActionRegistry

    Convention (cannot be enforced by ABC, enforced by register()):
      - Selector constants are ALL_CAPS class attributes
      - Every domain action_name starts with f"{site}_"
      - Inner action classes must subclass GlueAction, not ActionStrategy directly

    That last rule is about POMs, so it applies to web pages only. GlueAction
    exists to supply _build_pom, and _build_pom exists to make resolver=
    impossible to forget. A domain with no selectors has no POM layer to
    protect — it is Flow → Action, two layers rather than three — so a
    PageModule declaring a non-web `domain` subclasses ActionStrategy directly.
    See docs/universal-runner-plan.md §4.
    """

    site: str  # subclasses declare this as a plain class attribute

    #: The domain whose session these actions act on. Every shipped site is a
    #: browser site; a non-web domain overrides it. See bootstrap/session.py.
    domain: str = "web"

    #: Action names this module registers that deliberately break the
    #: f"{site}_" rule. Keep it empty unless there is a reason, and write the
    #: reason in the subclass docstring — an exemption nobody can explain is
    #: just an unenforced rule.
    unprefixed_actions: frozenset[str] = frozenset()

    @classmethod
    def register_actions(cls, registry, *actions):
        """
        Check the naming convention, then register.

        This is the enforcement base_page_module used only to *describe*. It
        was hand-copied into three of OpenLibrary's register() methods and
        missing from the other ten, so the rule held where it was least needed
        and not where a new site would trip over it.

        Returns the actions, so a caller that needs one back — to alias it,
        say — does not have to construct it separately.
        """
        prefix = f"{cls.site}_"
        for action in actions:
            name = action.action_name
            if name not in cls.unprefixed_actions and not name.startswith(prefix):
                raise ValueError(
                    f"{type(action).__name__}.action_name must start with "
                    f"{prefix!r}, got {name!r}. Action names share one flat "
                    f"namespace across every site. If the name is deliberate, "
                    f"add it to {cls.__name__}.unprefixed_actions and say why."
                )
            registry.register(action)
            logger.debug("Registered %s action: %s", cls.site, name)
        return actions

    @classmethod
    @abstractmethod
    def register(cls, registry) -> None:
        """
        Register this page's domain actions into the shared ActionRegistry.
        Called ONCE at startup in main.py — never per-request.

        Must enforce naming convention:
            if not action.action_name.startswith(cls.site + "_"):
                raise ValueError(...)
        """
