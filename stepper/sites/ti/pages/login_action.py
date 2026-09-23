"""sites/ti/pages/login_action.py — Stepper glue for the-internet login."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiLoginPage(PageModule):
    site = "ti"

    class TiLoginAction(GlueAction):
        """
        Log in to the-internet's secure area.

        Credentials come from TI_USER / TI_PASS, or poms/ti/config/config.yaml —
        the-internet publishes them on the login page itself.
        """

        action_name = "ti_login"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.login_page import LoginPage

                settings   = load_settings()
                driver     = self._driver(page)
                login_page = self._build_pom(LoginPage, driver, settings.base_url,
                                             page=page, resolver=resolver,
                                             behaviour=behaviour)

                username = step.extra.get("username") or settings.username
                password = step.extra.get("password") or settings.password

                if not username or not password:
                    return StepResult(
                        step=step, status="failed",
                        error=(
                            "ti_login: no credentials — set TI_USER / TI_PASS "
                            "or pass via step.extra"
                        ),
                    )

                logger.info("ti_login — logging in as %s", username)
                await login_page.open()
                if not await login_page.fill_username(username):
                    return StepResult(
                        step=step, status="failed",
                        error="ti_login: the username field was not filled "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )
                if not await login_page.fill_password(password):
                    return StepResult(
                        step=step, status="failed",
                        error="ti_login: the password field was not filled "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )
                if not await login_page.click_login():
                    return StepResult(
                        step=step, status="failed",
                        error="ti_login: the Login button was not clicked "
                              "(the selector matches nothing, or the element is "
                              "present but not interactable)",
                    )

                logger.info("ti_login ✓ — submitted login form")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_login failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiLoginAction())
