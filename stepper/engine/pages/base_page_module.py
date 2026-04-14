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
from abc import ABC, abstractmethod


class PageModule(ABC):
    """
    Abstract base for all page modules.

    Each concrete subclass represents one page of one site.

    Contract:
      - site   : short prefix string, e.g. "ol", "gr", "wiki"
      - register(): plugs this page's domain actions into the ActionRegistry

    Convention (cannot be enforced by ABC, enforced by register()):
      - Selector constants are ALL_CAPS class attributes
      - Every domain action_name starts with f"{site}_"
      - Inner action classes must subclass GlueAction, not ActionStrategy directly
    """

    site: str  # subclasses declare this as a plain class attribute

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
