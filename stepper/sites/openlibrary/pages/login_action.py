"""
sites/openlibrary/pages/login_action.py — Stepper glue for OL login.

Wraps LoginPage POM interactions into the named behavior "ol_ensure_login".
No selectors live here — they belong to LoginPage.
No flow logic lives in the POM — it belongs here (check → navigate → fill → submit).

JSON usage:
  { "action": "ol_ensure_login" }
"""

from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class OLLoginPage(PageModule):
    site = "ol"

    class OLEnsureLoginAction(GlueAction):
        """
        Ensure the browser session is authenticated with OpenLibrary.

        Behavior:
          1. Navigate to a protected page to detect whether a redirect occurs.
          2. Ask LoginPage.is_logged_in() — a positive selector check.
          3. If not logged in: open the login page, fill credentials, submit.

        All selectors are owned by LoginPage. Credentials come from Settings
        (env vars / config.yaml). JSON callers need only name the action.
        """
        action_name = "ol_ensure_login"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.login_page import LoginPage

                settings   = load_settings()
                driver     = self._driver(page)
                login_page = self._build_pom(LoginPage, driver, settings.base_url,
                                             settings.delays, page=page, resolver=resolver)

                if await login_page.is_session_live():
                    logger.info("ol_ensure_login ✓ — session already active")
                    return StepResult(step=step, status="passed")

                if not settings.username or not settings.password:
                    return StepResult(
                        step=step, status="failed",
                        error=(
                            "Login required but OPENLIBRARY_USERNAME / "
                            "OPENLIBRARY_PASSWORD are not set."
                        ),
                    )

                logger.info("ol_ensure_login — session expired, logging in as %s", settings.username)

                # is_session_live() navigates to a protected page, which OpenLibrary
                # redirects to the login form. The browser is likely already on the
                # login page — avoid a second navigation and just wait for the form.
                if "/account/login" in driver.current_url:
                    logger.info("ol_ensure_login — already on login page, skipping open()")
                    await login_page.wait_for_ready()
                else:
                    await login_page.open()        # navigate + wait_for_ready

                await login_page.fill_username(settings.username)
                await login_page.fill_password(settings.password)
                await login_page.submit()

                if not await login_page.is_logged_in():
                    return StepResult(
                        step=step, status="failed",
                        error="ol_ensure_login: still not logged in after submit",
                    )

                logger.info("ol_ensure_login ✓ — authenticated")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ol_ensure_login failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.OLEnsureLoginAction()
        if not action.action_name.startswith(cls.site + "_"):
            raise ValueError(
                f"{action.__class__.__name__}.action_name must start with "
                f"'{cls.site}_', got '{action.action_name}'"
            )
        registry.register(action)
        logger.debug("Registered page action: %s", action.action_name)
