"""
pathly/pages/home_screen_page.py — Pure POM for the Pathly home screen.

Single responsibility: selectors and raw interactions for the home screen.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage

logger = logging.getLogger(__name__)


class HomeScreenPage(BasePage):

    @property
    def url(self) -> str:
        return "electron://pathly-homescreen"

    async def open(self) -> None:
        """Navigation handled by CDP launcher. This method is intentionally a no-op for Electron pages."""

    @property
    def _tab_projects(self):
        return self._page.locator('[data-testid="homescreen-tab-projects"]')

    @property
    def _tab_getting_started(self):
        return self._page.locator('[data-testid="homescreen-tab-getting-started"]')

    @property
    def _tab_settings(self):
        return self._page.locator('[data-testid="homescreen-tab-settings"]')

    @property
    def _new_project_btn(self):
        return self._page.locator('[data-testid="homescreen-new-project-btn"]')

    @property
    def _project_cards(self):
        return self._page.locator('[data-testid="homescreen-project-card"]')

    @property
    def _open_btns(self):
        return self._page.locator('[data-testid="homescreen-open-btn"]')

    @property
    def _view_grid_btn(self):
        return self._page.locator('[data-testid="homescreen-view-grid-btn"]')

    @property
    def _view_list_btn(self):
        return self._page.locator('[data-testid="homescreen-view-list-btn"]')

    async def open_project(self, name: str) -> None:
        count = await self._project_cards.count()
        for i in range(count):
            card_text = await self._project_cards.nth(i).inner_text()
            if card_text.strip() == name:
                await self._open_btns.nth(i).click()
                return
        raise ValueError(f"Project '{name}' not found in HomeScreen")

    async def click_new_project(self) -> None:
        await self._new_project_btn.click()

    async def get_project_names(self) -> list[str]:
        count = await self._project_cards.count()
        if count == 0:
            return []
        return [
            (await self._project_cards.nth(i).inner_text()).strip()
            for i in range(count)
        ]
