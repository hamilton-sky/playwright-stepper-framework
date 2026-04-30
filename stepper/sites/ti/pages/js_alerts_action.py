"""sites/ti/pages/js_alerts_action.py — Stepper glue for the-internet JS alerts."""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiJsAlertsPage(PageModule):
    site = "ti"

    class TiHandleAlertsAction(GlueAction):
        action_name = "ti_handle_alerts"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.js_alerts_page import JsAlertsPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(JsAlertsPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()

                # JS Alert — accept
                page.once("dialog", lambda d: d.accept())
                await pom.click_js_alert_btn()

                # JS Confirm — dismiss
                page.once("dialog", lambda d: d.dismiss())
                await pom.click_js_confirm_btn()

                # JS Prompt — accept (empty input)
                page.once("dialog", lambda d: d.accept())
                await pom.click_js_prompt_btn()

                logger.info("ti_handle_alerts ✓ — handled alert, confirm, prompt")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_handle_alerts failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.TiHandleAlertsAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
