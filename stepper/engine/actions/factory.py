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


def build_default_registry(
    screenshots_dir: Path = Path("artifacts/screenshots"),
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
        ScreenshotAction, WaitAction,
        AssertCountAction, StoreCountAction,
        MeasurePerformanceAction,
        ForEachItemAction,
        ExtractDataAction, PaginateAction,
        EnsureLoginAction, ParallelAction,
    )

    registry     = ActionRegistry()
    for_each     = ForEachItemAction(action_factory=registry, screenshots_dir=screenshots_dir)
    ensure_login = EnsureLoginAction(action_factory=registry)
    parallel     = ParallelAction(action_factory=registry)

    return (
        registry
        .register(NavigateAction())
        .register(ClickAction())
        .register(FillAction())
        .register(HoverAction())
        .register(SelectAction())
        .register(ScreenshotAction(screenshots_dir))
        .register(WaitAction())
        .register(StoreCountAction())
        .register(AssertCountAction())
        .register(for_each)
        .register(ensure_login)
        .register(MeasurePerformanceAction())
        .register(ExtractDataAction())
        .register(PaginateAction())
        .register(parallel)
    )
