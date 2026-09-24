"""
pathly/pages/wizard_page.py — Pure POM for the Pathly FlowWizard.

Single responsibility: selectors and raw interactions for the FlowWizard.
No flow logic. No assertions.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class WizardPage(BasePage):

    class Locators:
        FLOWS_ADD_BTN = Locator(
            css='[data-testid="sidebar-flows-add-btn"]',
            description="add flow button in the sidebar, which opens the wizard",
        )
        BTN_NEXT = Locator(
            css='[data-testid="wizard-btn-next"]', description="wizard Next button",
        )
        BTN_BACK = Locator(
            css='[data-testid="wizard-btn-back"]', description="wizard Back button",
        )
        BTN_CANCEL = Locator(
            css='[data-testid="wizard-btn-cancel"]', description="wizard Cancel button",
        )
        BTN_SAVE = Locator(
            css='[data-testid="wizard-btn-save"]', description="wizard Save button",
        )
        START_TEMPLATE = Locator(
            css='[data-testid="wizard-start-template"]',
            description="start from a template option",
        )
        START_BLANK = Locator(
            css='[data-testid="wizard-start-blank"]',
            description="start from blank option",
        )
        INPUT_NAME = Locator(
            css='[data-testid="wizard-input-name"]', description="flow name input",
        )
        INPUT_DESCRIPTION = Locator(
            css='[data-testid="wizard-input-description"]',
            description="flow description input",
        )

        #: Templates are addressed by id, so this one is built per call rather
        #: than declared — see `_template_locator`.
        TEMPLATE_FMT = '[data-testid="wizard-template-{template_id}"]'

    @property
    def url(self) -> str:
        return "electron://pathly-wizard"

    async def open(self) -> None:
        """No-op: the CDP session attaches to whatever the app is showing."""

    @classmethod
    def _template_locator(cls, template_id: str) -> Locator:
        """
        One template tile, by id.

        A Locator built at call time rather than declared in Locators: the id
        is a run-time value, so there is no fixed element to name. It still
        goes through _interact, so it still gets the cascade.
        """
        return Locator(
            css=cls.Locators.TEMPLATE_FMT.format(template_id=template_id),
            description=f"{template_id} template tile in the wizard",
        )

    # Every interaction below returns _interact's success flag rather than
    # discarding it. _interact does not raise for the interaction itself: a
    # missing selector, a resolver confidence below CONFIDENCE_WARN, or a
    # click that does not land all come back as False. Swallowing that here
    # is what let pathly_wizard_smoke — open → template → name → next x4 →
    # save → screenshot, with no assertion anywhere — report ten passed
    # steps against an app whose wizard never opened. The POM still does not
    # assert; it reports, and the glue decides.

    async def open_wizard(self) -> bool:
        return await self._interact(self.Locators.FLOWS_ADD_BTN, "click")

    async def select_template(self, template_id: str) -> bool:
        return await self._interact(self._template_locator(template_id), "click")

    async def set_name(self, name: str) -> bool:
        return await self._interact(self.Locators.INPUT_NAME, "fill", value=name)

    async def set_description(self, description: str) -> bool:
        return await self._interact(self.Locators.INPUT_DESCRIPTION, "fill", value=description)

    async def click_next(self) -> bool:
        return await self._interact(self.Locators.BTN_NEXT, "click")

    async def click_back(self) -> bool:
        return await self._interact(self.Locators.BTN_BACK, "click")

    async def click_cancel(self) -> bool:
        return await self._interact(self.Locators.BTN_CANCEL, "click")

    async def click_save(self) -> bool:
        return await self._interact(self.Locators.BTN_SAVE, "click")
