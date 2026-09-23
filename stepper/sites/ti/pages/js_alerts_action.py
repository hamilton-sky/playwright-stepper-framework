"""sites/ti/pages/js_alerts_action.py — Stepper glue for the-internet JS alerts."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiJsAlertsPage(PageModule):
    site = "ti"

    class TiHandleAlertsAction(GlueAction):
        """
        Trigger each JavaScript dialog and dismiss it.

        Covers the alert, confirm and prompt buttons in turn, reading the result
        text the page writes after each one.
        """

        action_name = "ti_handle_alerts"

        @staticmethod
        def _dialog_handler(respond: str):
            """
            One dialog responder, as a named function so it can be removed
            again — a lambda would be a fresh object every call.

            It must *return* the coroutine. In the async API `dialog.accept()`
            does not answer the dialog, it builds a coroutine, and Playwright's
            emitter schedules whatever the handler returns. Dropping it leaves
            the dialog unanswered, which blocks the page: the next click times
            out and the guard above reports "the button was not clicked" — true,
            but for a reason three steps removed from the cause.
            """
            def _handle(dialog):
                return getattr(dialog, respond)()
            return _handle

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

                # Each click is paired with the handler for the dialog it
                # raises, and the handler comes off again whether or not the
                # click landed. page.once() only removes itself when it
                # *fires*: a missed click used to leave it attached, and with
                # retry > 0 the next attempt registered a second one — two
                # handlers racing to accept the same dialog, the loser hitting
                # "Dialog has already been handled". Codex caught it on #31.
                for label, click, respond in (
                    ("JS Alert",   pom.click_js_alert_btn,   "accept"),
                    ("JS Confirm", pom.click_js_confirm_btn, "dismiss"),
                    ("JS Prompt",  pom.click_js_prompt_btn,  "accept"),
                ):
                    handler = self._dialog_handler(respond)
                    page.once("dialog", handler)
                    try:
                        clicked = await click()
                    finally:
                        # A no-op once the handler has fired and removed
                        # itself; Playwright tolerates both states.
                        page.remove_listener("dialog", handler)

                    if not clicked:
                        return StepResult(
                            step=step, status="failed",
                            error=f"ti_handle_alerts: the {label} button was not "
                                  f"clicked (the selector matches nothing, or the "
                                  f"element is present but not interactable)",
                        )

                logger.info("ti_handle_alerts ✓ — handled alert, confirm, prompt")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_handle_alerts failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiHandleAlertsAction())
