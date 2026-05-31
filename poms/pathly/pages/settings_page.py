"""
pathly/pages/settings_page.py — Pure POM for the Pathly settings page.

Single responsibility: selectors and raw interactions for the settings panel.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage

logger = logging.getLogger(__name__)


class SettingsPage(BasePage):

    @property
    def url(self) -> str:
        return "electron://pathly-settings"

    async def open(self) -> None:
        """Navigation handled by CDP launcher. This method is intentionally a no-op for Electron pages."""

    @property
    def _save_btn(self):
        return self._page.locator('[data-testid="settings-save-btn"]')

    @property
    def _fsm_command_input(self):
        return self._page.locator('[data-testid="settings-fsm-command-input"]')

    @property
    def _routing_llm(self):
        return self._page.locator('[data-testid="settings-routing-llm"]')

    @property
    def _routing_python(self):
        return self._page.locator('[data-testid="settings-routing-python"]')

    async def get_routing_engine(self) -> str:
        llm_text = await self._routing_llm.inner_text()
        return "llm" if "●" in llm_text else "python-fsm"

    async def set_routing_engine(self, engine: str) -> None:
        if engine not in ["llm", "python", "python-fsm"]:
            raise ValueError(f"Invalid routing engine '{engine}'. Must be 'llm', 'python', or 'python-fsm'.")
        if engine == "llm":
            await self._routing_llm.click()
        else:
            await self._routing_python.click()

    async def set_fsm_command(self, cmd: str) -> None:
        await self._fsm_command_input.clear()
        await self._fsm_command_input.fill(cmd)

    async def save_settings(self) -> None:
        await self._save_btn.click()
