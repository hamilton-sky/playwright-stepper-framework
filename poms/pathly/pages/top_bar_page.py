"""
pathly/pages/top_bar_page.py — Pure POM for the Pathly top bar and sidebar.

Single responsibility: selectors and raw interactions for the top bar controls.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class TopBarPage(BasePage):

    class Locators:
        SIDEBAR_TOGGLE = Locator(
            css='[data-testid="topbar-sidebar-toggle"]',
            description="sidebar collapse toggle",
        )
        PANEL_FLOW = Locator(
            css='[data-testid="topbar-panel-flow"]',
            description="Flow panel tab",
        )
        PANEL_MONITOR = Locator(
            css='[data-testid="topbar-panel-monitor"]',
            description="Monitor panel tab",
        )
        CHAT_TOGGLE = Locator(
            css='[data-testid="topbar-chat-toggle"]',
            description="chat panel toggle",
        )
        THEME_TOGGLE = Locator(
            css='[data-testid="topbar-theme-toggle"]',
            description="light/dark theme toggle",
        )
        SIDEBAR_NAV_SETTINGS = Locator(
            css='[data-testid="sidebar-nav-settings"]',
            description="Settings item in the sidebar",
        )
        SIDEBAR_NAV_MONITOR = Locator(
            css='[data-testid="sidebar-nav-monitor"]',
            description="Monitor item in the sidebar",
        )

    @property
    def url(self) -> str:
        return "electron://pathly-topbar"

    async def open(self) -> None:
        """No-op: the CDP session attaches to whatever the app is showing."""

    async def navigate_to_panel(self, panel: str) -> bool:
        """
        Settings is reached through the sidebar, the other two through the top
        bar — the app puts them in different places, so this does too.
        """
        panels = {"flow": self.Locators.PANEL_FLOW,
                  "monitor": self.Locators.PANEL_MONITOR,
                  "settings": self.Locators.SIDEBAR_NAV_SETTINGS}
        if panel not in panels:
            raise ValueError(
                f"Invalid panel {panel!r}. Expected one of {sorted(panels)}."
            )
        return await self._interact(panels[panel], "click")

    async def toggle_sidebar(self) -> bool:
        return await self._interact(self.Locators.SIDEBAR_TOGGLE, "click")

    async def toggle_chat(self) -> bool:
        return await self._interact(self.Locators.CHAT_TOGGLE, "click")

    async def toggle_theme(self) -> bool:
        return await self._interact(self.Locators.THEME_TOGGLE, "click")
