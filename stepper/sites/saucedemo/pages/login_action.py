"""
sites/saucedemo/pages/login_action.py — Stepper glue for SauceDemo login.

Wraps LoginPage POM interactions into the named behavior "sd_login".

No selectors here — they belong to LoginPage.
No flow logic in the POM — it belongs here (check → fill → submit → assert).

JSON usage:
  { "action": "sd_login" }

Credentials come from SAUCEDEMO_USERNAME / SAUCEDEMO_PASSWORD env vars
or poms/saucedemo/config/config.yaml.
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class SDLoginPage(PageModule):
    site = "sd"

    class SDLoginAction(GlueAction):
        """
        Log in to SauceDemo.

        Behavior:
          1. Check is_logged_in() — skip if already authenticated.
          2. Open login page, fill username + password, submit.
          3. Assert is_logged_in() — fail with clear message if login rejected.

        Credentials: SAUCEDEMO_USERNAME / SAUCEDEMO_PASSWORD (env) or config.yaml.
        Override per-step via step.extra["username"] / step.extra["password"].

        JSON usage:
          { "action": "sd_login" }
          { "action": "sd_login", "extra": { "username": "problem_user", "password": "secret_sauce" } }
        """
        action_name = "sd_login"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.saucedemo.config import load_settings
                from poms.saucedemo.pages.login_page import LoginPage

                settings   = load_settings()
                driver     = self._driver(page)
                login_page = self._build_pom(LoginPage, driver, settings.base_url,
                                             page=page, resolver=resolver)

                if await login_page.is_logged_in():
                    logger.info("sd_login ✓ — already authenticated")
                    return StepResult(step=step, status="passed")

                username = step.extra.get("username") or settings.username
                password = step.extra.get("password") or settings.password

                if not username or not password:
                    return StepResult(
                        step=step, status="failed",
                        error=(
                            "sd_login: no credentials — set SAUCEDEMO_USERNAME / "
                            "SAUCEDEMO_PASSWORD or pass via step.extra"
                        ),
                    )

                logger.info("sd_login — logging in as %s", username)
                await login_page.open()
                await login_page.fill_username(username)
                await login_page.fill_password(password)
                await login_page.submit()

                if not await login_page.is_logged_in():
                    error_msg = await login_page.get_error_message()
                    return StepResult(
                        step=step, status="failed",
                        error=f"sd_login: login failed — {error_msg or 'unknown error'}",
                    )

                logger.info("sd_login ✓ — authenticated as %s", username)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("sd_login failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.SDLoginAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
