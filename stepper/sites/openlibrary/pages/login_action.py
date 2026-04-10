"""
sites/openlibrary/pages/login_action.py — Stepper action module for OL login.

Wraps shared_poms.auth.ensure_logged_in() into a named Stepper action so
JSON workflows never need to contain CSS selectors for the login form.

JSON usage:
  { "action": "ol_ensure_login" }

Dependency direction: sites.openlibrary → stepper  (correct)
                      sites.openlibrary → shared_poms  (correct)
"""

from __future__ import annotations
import logging

from stepper.interfaces import ActionStrategy, StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule

logger = logging.getLogger(__name__)


class OLLoginPage(PageModule):
    site = "ol"

    class OLEnsureLoginAction(ActionStrategy):
        """
        Ensure the browser session is authenticated with OpenLibrary.

        Delegates entirely to shared_poms.auth.ensure_logged_in(), which owns
        all credential-form selectors (#username, #password, .cta-btn--primary).
        JSON callers need only name the action — no CSS knowledge required.

        JSON usage:
          { "action": "ol_ensure_login" }
        """
        action_name = "ol_ensure_login"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from shared_poms.config import load_settings
                from shared_poms.driver import PlaywrightDriver
                from shared_poms.auth import ensure_logged_in

                settings = load_settings()
                driver   = PlaywrightDriver(page)

                await ensure_logged_in(
                    driver,
                    settings.username,
                    settings.password,
                    settings.base_url,
                )

                logger.info("ol_ensure_login ✓ — session authenticated")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error(f"ol_ensure_login failed: {e}")
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
        logger.debug(f"Registered page action: {action.action_name}")
