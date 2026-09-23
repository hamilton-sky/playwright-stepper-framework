"""sites/ti/pages/secure_action.py — Stepper glue for the-internet secure area."""
from __future__ import annotations
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiSecurePage(PageModule):
    site = "ti"

    class TiViewSecureAction(GlueAction):
        """Wait for the secure area and store its flash message."""

        action_name = "ti_view_secure"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.secure_page import SecurePage

                settings    = load_settings()
                driver      = self._driver(page)
                secure_page = self._build_pom(SecurePage, driver, settings.base_url,
                                              page=page, resolver=resolver,
                                              behaviour=behaviour)

                await secure_page.wait_for_ready()

                # This step's whole job is to confirm the secure area was
                # reached. `if flash:` meant no flash was indistinguishable
                # from a flash — a bad password lands on /login and this still
                # reported passed, so the login flow above it could not fail.
                flash = await secure_page.get_flash_message()
                if not flash:
                    return StepResult(
                        step=step, status="failed",
                        error="ti_view_secure: no success flash on the page — the "
                              f"secure area was not reached (url: {page.url})",
                    )

                key = step.extra.get("key") or "ti_secure_flash"
                context.store(key, flash)
                logger.info("ti_view_secure ✓ — flash: %s", flash)
                return StepResult(step=step, status="passed", output={key: flash})

            except Exception as e:
                logger.error("ti_view_secure failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiViewSecureAction())
