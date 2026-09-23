"""
pathly/pages/settings_page.py — Pure POM for the Pathly settings page.

Single responsibility: selectors and raw interactions for the settings panel.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class SettingsPage(BasePage):

    class Locators:
        SAVE_BTN = Locator(
            css='[data-testid="settings-save-btn"]',
            description="save settings button",
        )
        FSM_COMMAND_INPUT = Locator(
            css='[data-testid="settings-fsm-command-input"]',
            description="FSM command input field",
        )
        ROUTING_LLM = Locator(
            css='[data-testid="settings-routing-llm"]',
            description="LLM routing engine option",
        )
        ROUTING_PYTHON = Locator(
            css='[data-testid="settings-routing-python"]',
            description="Python FSM routing engine option",
        )

        #: Read-only: the selected option is read, not clicked, to report state.
        ROUTING_LLM_CSS = '[data-testid="settings-routing-llm"]'

    @property
    def url(self) -> str:
        return "electron://pathly-settings"

    async def open(self) -> None:
        """No-op: the CDP session attaches to whatever the app is showing."""

    async def get_routing_engine(self) -> str:
        """
        Which engine is selected, read from the bullet the app renders.

        The marker is a '●' in the LLM option's text — the app draws no other
        state we can see from outside.
        """
        text = await self._page.locator(self.Locators.ROUTING_LLM_CSS).inner_text()
        return "llm" if "●" in text else "python-fsm"

    async def set_routing_engine(self, engine: str) -> bool:
        if engine not in ("llm", "python", "python-fsm"):
            raise ValueError(
                f"Invalid routing engine {engine!r}. "
                f"Expected 'llm', 'python' or 'python-fsm'."
            )
        target = (self.Locators.ROUTING_LLM if engine == "llm"
                  else self.Locators.ROUTING_PYTHON)
        return await self._interact(target, "click")

    async def set_fsm_command(self, cmd: str) -> bool:
        return await self._interact(self.Locators.FSM_COMMAND_INPUT, "fill", value=cmd)

    async def save_settings(self) -> bool:
        return await self._interact(self.Locators.SAVE_BTN, "click")
