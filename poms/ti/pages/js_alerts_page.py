"""ti/pages/js_alerts_page.py — Pure POM for the-internet JS alerts page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class JsAlertsPage(BasePage):

    class Locators:
        JS_ALERT_BTN = Locator(
            role="button", name="Click for JS Alert",
            description="button that triggers a JS alert dialog",
        )
        JS_CONFIRM_BTN = Locator(
            role="button", name="Click for JS Confirm",
            description="button that triggers a JS confirm dialog",
        )
        JS_PROMPT_BTN = Locator(
            role="button", name="Click for JS Prompt",
            description="button that triggers a JS prompt dialog",
        )

        # Read-only state check
        RESULT = "#result"

    @property
    def url(self) -> str:
        return f"{self.base_url}/javascript_alerts"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector("button", timeout=15_000)
        except Exception:
            pass

    async def click_js_alert_btn(self) -> None:
        await self._interact(self.Locators.JS_ALERT_BTN, "click")

    async def click_js_confirm_btn(self) -> None:
        await self._interact(self.Locators.JS_CONFIRM_BTN, "click")

    async def click_js_prompt_btn(self) -> None:
        await self._interact(self.Locators.JS_PROMPT_BTN, "click")

    async def get_result(self) -> str | None:
        el = await self._driver.query_selector(self.Locators.RESULT)
        if el:
            return (await el.inner_text()).strip()
        return None
