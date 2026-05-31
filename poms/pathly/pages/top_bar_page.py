"""
pathly/pages/top_bar_page.py — Pure POM for the Pathly top bar and sidebar.

Single responsibility: selectors and raw interactions for the top bar controls.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage

logger = logging.getLogger(__name__)


class TopBarPage(BasePage):

    @property
    def url(self) -> str:
        return "electron://pathly-topbar"

    async def open(self) -> None:
        """Navigation handled by CDP launcher. This method is intentionally a no-op for Electron pages."""

    @property
    def _sidebar_toggle(self):
        return self._page.locator('[data-testid="topbar-sidebar-toggle"]')

    @property
    def _panel_flow(self):
        return self._page.locator('[data-testid="topbar-panel-flow"]')

    @property
    def _panel_monitor(self):
        return self._page.locator('[data-testid="topbar-panel-monitor"]')

    @property
    def _chat_toggle(self):
        return self._page.locator('[data-testid="topbar-chat-toggle"]')

    @property
    def _theme_toggle(self):
        return self._page.locator('[data-testid="topbar-theme-toggle"]')

    @property
    def _sidebar_nav_settings(self):
        return self._page.locator('[data-testid="sidebar-nav-settings"]')

    async def navigate_to_panel(self, panel: str) -> None:
        if panel not in ["flow", "monitor", "settings"]:
            raise ValueError(f"Invalid panel '{panel}'. Must be 'flow', 'monitor', or 'settings'.")
        if panel == "flow":
            await self._panel_flow.click()
        elif panel == "monitor":
            await self._panel_monitor.click()
        else:
            await self._sidebar_nav_settings.click()

    async def toggle_chat(self) -> None:
        await self._chat_toggle.click()

    async def toggle_theme(self) -> None:
        await self._theme_toggle.click()
