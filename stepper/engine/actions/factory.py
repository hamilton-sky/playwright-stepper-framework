"""
actions/factory.py — ActionFactory implementation.

Pattern: Factory + Registry
  Actions register themselves by action_name.
  Factory looks up and returns the right instance.

OCP: Register a new action without touching existing code.
DIP: Callers depend on ActionFactory interface, not this class.
"""

from __future__ import annotations
import logging
from pathlib import Path
from engine.interfaces import ActionFactory, ActionStrategy

logger = logging.getLogger(__name__)


class ActionRegistry(ActionFactory):
    """
    Registry-based factory.
    Actions are registered by their action_name string.

    Usage:
        registry = ActionRegistry()
        registry.register(ClickAction())
        action = registry.create("click")
    """

    def __init__(self):
        self._registry: dict[str, ActionStrategy] = {}

    def register(self, action: ActionStrategy):
        self._registry[action.action_name] = action
        logger.debug(f"Registered action: {action.action_name}")
        return self  # fluent API → registry.register(A).register(B)

    def create(self, action_name: str) -> ActionStrategy:
        action = self._registry.get(action_name)
        if not action:
            raise ValueError(
                f"Unknown action: '{action_name}'. "
                f"Registered: {list(self._registry.keys())}"
            )
        return action

    # ── Read API ──────────────────────────────────────────────────────────────
    # Callers that need to enumerate actions (PlanValidator, ActionSchemaExtractor)
    # go through these instead of reaching into the backing dict.

    def names(self) -> list[str]:
        """Sorted names of every registered action, aliases included."""
        return sorted(self._registry)

    def items(self) -> list[tuple[str, ActionStrategy]]:
        """(name, action) pairs in registration order. Aliases appear twice."""
        return list(self._registry.items())

    def __contains__(self, action_name: object) -> bool:
        return action_name in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    # ── Aliasing ──────────────────────────────────────────────────────────────

    def alias(self, alias_name: str, action_name: str):
        """
        Bind a second name to an already-registered action.

        Both names resolve to the *same instance*, so an action that carries
        state stays consistent whichever name a workflow uses.

            registry.register(OLCollectBooksAction())
            registry.alias("ol_collect_books", "collect_items")

        Raises:
            ValueError: if the target is not registered, or if the alias name is
                already taken by a different action (silently shadowing one
                action with another is never intended).
        """
        target = self._registry.get(action_name)
        if target is None:
            raise ValueError(
                f"Cannot alias '{alias_name}' → '{action_name}': "
                f"'{action_name}' is not registered. Register it first."
            )
        existing = self._registry.get(alias_name)
        if existing is not None and existing is not target:
            raise ValueError(
                f"Cannot alias '{alias_name}' → '{action_name}': "
                f"'{alias_name}' is already registered to "
                f"{type(existing).__name__}."
            )
        self._registry[alias_name] = target
        logger.debug(f"Aliased action: {alias_name} → {action_name}")
        return self  # fluent, like register()


def build_default_registry(
    screenshots_dir: Path = Path("artifacts/screenshots"),
    browser_launcher=None,
) -> ActionRegistry:
    """
    Builds the default registry with all Phase 1 + Phase 2 actions.

    To add a new action:
      1. Write your ActionStrategy subclass in strategies.py
      2. Add one .register() call here.
      Done. Zero other changes. (OCP)

    Note: collect_items is an OpenLibrary-specific action — it is registered
    by OLSearchPage.register() in main.py, not here.
    """
    from engine.actions.strategies import (
        NavigateAction, ClickAction, FillAction, HoverAction, SelectAction,
        ScreenshotAction, WaitAction, ScrollToAction,
        AssertCountAction, StoreCountAction,
        MeasurePerformanceAction, VisualCompareAction,
        ForEachItemAction,
        ExtractDataAction, PaginateAction,
        EnsureLoginAction, ParallelAction,
        LoadTestDataAction,
        AssertTextAction, AssertVisibleAction, StoreAction, KeyboardPressAction,
    )

    registry     = ActionRegistry()
    for_each     = ForEachItemAction(action_factory=registry, screenshots_dir=screenshots_dir)
    ensure_login = EnsureLoginAction(action_factory=registry)
    paginate     = PaginateAction(action_factory=registry)
    parallel     = ParallelAction(action_factory=registry, browser_launcher=browser_launcher)

    return (
        registry
        .register(NavigateAction())
        .register(ClickAction())
        .register(FillAction())
        .register(HoverAction())
        .register(SelectAction())
        .register(ScreenshotAction(screenshots_dir))
        .register(WaitAction())
        .register(ScrollToAction())
        .register(StoreCountAction())
        .register(AssertCountAction())
        .register(for_each)
        .register(ensure_login)
        .register(MeasurePerformanceAction())
        .register(VisualCompareAction())
        .register(ExtractDataAction())
        .register(paginate)
        .register(parallel)
        .register(LoadTestDataAction())
        .register(AssertTextAction())
        .register(AssertVisibleAction())
        .register(StoreAction())
        .register(KeyboardPressAction())
    )
