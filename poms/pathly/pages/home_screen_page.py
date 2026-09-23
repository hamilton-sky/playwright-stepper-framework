"""
pathly/pages/home_screen_page.py — Pure POM for the Pathly home screen.

Single responsibility: selectors and raw interactions for the home screen.
No flow logic. No assertions.

Every selector is a `data-testid` that must exist in the Pathly Studio source
(`pathly-adapters/studio/src/renderer/src/components/`). This harness is only
as good as those attributes: add one there before adding an element here.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class HomeScreenPage(BasePage):

    class Locators:
        # ── Interactive → Locator objects, so _interact takes the cascade ────
        TAB_PROJECTS = Locator(
            css='[data-testid="homescreen-tab-projects"]',
            description="Projects tab on the home screen",
        )
        TAB_GETTING_STARTED = Locator(
            css='[data-testid="homescreen-tab-getting-started"]',
            description="Getting Started tab on the home screen",
        )
        TAB_SETTINGS = Locator(
            css='[data-testid="homescreen-tab-settings"]',
            description="Settings tab on the home screen",
        )
        NEW_PROJECT_BTN = Locator(
            css='[data-testid="homescreen-new-project-btn"]',
            description="new project button",
        )
        VIEW_GRID_BTN = Locator(
            css='[data-testid="homescreen-view-grid-btn"]',
            description="grid view toggle",
        )
        VIEW_LIST_BTN = Locator(
            css='[data-testid="homescreen-view-list-btn"]',
            description="list view toggle",
        )

        # ── Collections → plain CSS, per pom-layer.md ────────────────────────
        # These are counted and indexed rather than resolved to one element,
        # which is what SauceDemo's inventory page does with its item list.
        # The cascade resolves a single element; it has no nth() to offer.
        PROJECT_CARDS = '[data-testid="homescreen-project-card"]'
        OPEN_BTNS     = '[data-testid="homescreen-open-btn"]'

    @property
    def url(self) -> str:
        return "electron://pathly-homescreen"

    async def open(self) -> None:
        """No-op: the CDP session attaches to whatever the app is showing."""

    async def click_new_project(self) -> None:
        await self._interact(self.Locators.NEW_PROJECT_BTN, "click")

    async def open_tab(self, tab: str) -> None:
        tabs = {"projects": self.Locators.TAB_PROJECTS,
                "getting-started": self.Locators.TAB_GETTING_STARTED,
                "settings": self.Locators.TAB_SETTINGS}
        if tab not in tabs:
            raise ValueError(f"Unknown tab {tab!r}. Expected one of {sorted(tabs)}.")
        await self._interact(tabs[tab], "click")

    async def set_view(self, view: str) -> None:
        views = {"grid": self.Locators.VIEW_GRID_BTN, "list": self.Locators.VIEW_LIST_BTN}
        if view not in views:
            raise ValueError(f"Unknown view {view!r}. Expected 'grid' or 'list'.")
        await self._interact(views[view], "click")

    async def get_project_names(self) -> list[str]:
        cards = self._page.locator(self.Locators.PROJECT_CARDS)
        return [(await cards.nth(i).inner_text()).strip()
                for i in range(await cards.count())]

    async def open_project(self, name: str) -> None:
        cards = self._page.locator(self.Locators.PROJECT_CARDS)
        opens = self._page.locator(self.Locators.OPEN_BTNS)
        for i in range(await cards.count()):
            if (await cards.nth(i).inner_text()).strip() == name:
                await opens.nth(i).click()
                return
        raise ValueError(f"Project {name!r} not found on the home screen")
