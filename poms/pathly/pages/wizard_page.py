"""
pathly/pages/wizard_page.py — Pure POM for the Pathly FlowWizard.

Single responsibility: selectors and raw interactions for the FlowWizard.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage

logger = logging.getLogger(__name__)


class WizardPage(BasePage):

    url = "electron://pathly-wizard"

    async def open(self) -> None:
        """Navigation handled by CDP launcher. This method is intentionally a no-op for Electron pages."""

    @property
    def _flows_add_btn(self):
        return self._page.locator('[data-testid="sidebar-flows-add-btn"]')

    @property
    def _btn_next(self):
        return self._page.locator('[data-testid="wizard-btn-next"]')

    @property
    def _btn_back(self):
        return self._page.locator('[data-testid="wizard-btn-back"]')

    @property
    def _btn_cancel(self):
        return self._page.locator('[data-testid="wizard-btn-cancel"]')

    @property
    def _btn_save(self):
        return self._page.locator('[data-testid="wizard-btn-save"]')

    @property
    def _start_template(self):
        return self._page.locator('[data-testid="wizard-start-template"]')

    @property
    def _start_blank(self):
        return self._page.locator('[data-testid="wizard-start-blank"]')

    @property
    def _input_name(self):
        return self._page.locator('[data-testid="wizard-input-name"]')

    @property
    def _input_description(self):
        return self._page.locator('[data-testid="wizard-input-description"]')

    def template(self, template_id: str):
        return self._page.locator(f'[data-testid="wizard-template-{template_id}"]')

    async def open_wizard(self) -> None:
        await self._flows_add_btn.click()

    async def select_template(self, template_id: str) -> None:
        await self.template(template_id).click()

    async def set_name(self, name: str) -> None:
        await self._input_name.click()
        await self._input_name.fill(name)

    async def click_next(self) -> None:
        await self._btn_next.click()

    async def click_save(self) -> None:
        await self._btn_save.click()
