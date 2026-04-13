"""
shared/interfaces.py — POM and browser driver contracts.

These interfaces define the browser driver adapter and configuration
contracts used by all site Page Object Models.

Concrete implementations:
  IBrowserDriver  → shared/driver.py:PlaywrightDriver
  IElementHandle  → shared/driver.py:PlaywrightElementHandle
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


# ──────────────────────────────────────────────────────────
# CONFIGURATION VALUE OBJECTS
# ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Delays:
    """Rate limiting & delay configuration (milliseconds)."""
    page_load_wait_ms: int = 1000
    between_actions_ms: int = 300
    between_pagination_ms: int = 1000
    post_login_wait_ms: int = 1000
    retry_backoff_ms: int = 2000
    search_submit_delay_ms: int = 500
    max_search_pages: int = 5


# ──────────────────────────────────────────────────────────
# BROWSER DRIVER — Playwright isolation layer
# ──────────────────────────────────────────────────────────

class IElementHandle(ABC):
    """
    Wraps a single DOM element handle.
    Concrete: PlaywrightElementHandle in shared/driver.py
    """

    @abstractmethod
    async def inner_text(self) -> str: ...

    @abstractmethod
    async def get_attribute(self, name: str) -> str | None: ...

    @abstractmethod
    async def click(self) -> None: ...

    @abstractmethod
    async def query_selector(self, selector: str) -> "IElementHandle | None": ...


class IBrowserDriver(ABC):
    """
    Wraps all browser operations needed by POMs and authentication.
    Concrete: PlaywrightDriver in shared/driver.py

    DIP: POMs, auth, and performance code depend on this
    interface — never on Playwright's Page directly.
    """

    @abstractmethod
    async def goto(self, url: str, *,
                   wait_until: str = "domcontentloaded",
                   timeout: int = 30_000) -> None: ...

    @abstractmethod
    async def fill(self, selector: str, value: str) -> None: ...

    @abstractmethod
    async def click(self, selector: str) -> None: ...

    @abstractmethod
    async def press(self, selector: str, key: str) -> None: ...

    @abstractmethod
    async def query_selector(self, selector: str) -> IElementHandle | None: ...

    @abstractmethod
    async def query_selector_all(self, selector: str) -> list[IElementHandle]: ...

    @abstractmethod
    async def wait_for_selector(self, selector: str, *,
                                timeout: int = 30_000) -> IElementHandle | None: ...

    @abstractmethod
    async def wait_for_load_state(self, state: str) -> None: ...

    @abstractmethod
    async def screenshot(self, path: str) -> None: ...

    @abstractmethod
    async def evaluate(self, js_code: str) -> Any: ...

    @abstractmethod
    async def locator_count(self, selector: str) -> int: ...

    @abstractmethod
    async def get_by_text(self, text: str, *,
                          exact: bool = True) -> Any: ...

    @abstractmethod
    def get_by_role(self, role: str, *,
                    name: str | None = None,
                    exact: bool = True) -> Any: ...

    @abstractmethod
    def get_by_label(self, text: str, *, exact: bool = True) -> Any: ...

    @abstractmethod
    def get_by_placeholder(self, text: str, *, exact: bool = True) -> Any: ...

    @abstractmethod
    def get_by_test_id(self, test_id: str) -> Any: ...

    @abstractmethod
    def locator(self, selector: str) -> Any: ...

    @property
    @abstractmethod
    def current_url(self) -> str: ...
