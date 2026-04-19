"""
sites/phptravels/pages/login_action.py — Stepper glue for phpTravels login.

Wraps LoginPage into the named behavior "pt_login".

JSON usage:
  { "action": "pt_login" }
  { "action": "pt_login", "extra": { "email": "user@example.com", "password": "secret" } }

Credentials come from PHPTRAVELS_EMAIL / PHPTRAVELS_PASSWORD env vars
or poms/phpTravels/config.py defaults.
"""
from __future__ import annotations
import logging

from engine.browser.human_behaviour import HumanBehaviour
from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PTLoginPage(PageModule):
    site = "pt"

    class PTLoginAction(GlueAction):
        """
        Log in to phpTravels.

        Behavior:
          1. Check is_logged_in() — skip if already authenticated.
          2. Open login page, fill email + password, submit.
          3. Assert is_logged_in() — fail with clear message if login rejected.

        JSON usage:
          { "action": "pt_login" }
        """
        action_name = "pt_login"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
            behaviour: HumanBehaviour,
        ) -> StepResult:
            try:
                from poms.phpTravels.config import load_settings
                from poms.phpTravels.pages.login_page import LoginPage

                settings   = load_settings()
                driver     = self._driver(page)
                login_page = self._build_pom(LoginPage, driver, settings.base_url,
                                             page=page, resolver=resolver, behaviour=behaviour)

                if await login_page.is_logged_in():
                    logger.info("pt_login ✓ — already authenticated")
                    return StepResult(step=step, status="passed")

                email    = step.extra.get("email")    or settings.email
                password = step.extra.get("password") or settings.password

                if not email or not password:
                    return StepResult(
                        step=step, status="failed",
                        error=(
                            "pt_login: no credentials — set PHPTRAVELS_EMAIL / "
                            "PHPTRAVELS_PASSWORD or pass via step.extra"
                        ),
                    )

                logger.info("pt_login — logging in as %s", email)
                await login_page.open()
                await login_page.fill_email(email)
                await login_page.fill_password(password)
                await login_page.submit()

                if not await login_page.is_logged_in():
                    error_msg = await login_page.get_error_message()
                    return StepResult(
                        step=step, status="failed",
                        error=f"pt_login: login failed — {error_msg or 'unknown error'}",
                    )

                logger.info("pt_login ✓ — authenticated as %s", email)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("pt_login failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.PTLoginAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
