"""sites/ti/pages/windows_action.py — Stepper glue for the-internet new window."""
from __future__ import annotations
import asyncio
import logging

from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class TiWindowsPage(PageModule):
    site = "ti"

    class TiOpenNewWindowAction(GlueAction):
        """Open the new-window link and switch to the window it opens."""

        action_name = "ti_open_new_window"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext, behaviour=None,
        ) -> StepResult:
            try:
                from poms.ti.config import load_settings
                from poms.ti.pages.windows_page import WindowsPage

                settings = load_settings()
                driver   = self._driver(page)
                pom      = self._build_pom(WindowsPage, driver, settings.base_url,
                                           page=page, resolver=resolver,
                                           behaviour=behaviour)

                await pom.open()

                # A plain listener rather than expect_page(), for one
                # reason: returning from inside `async with expect_page()`
                # does not skip __aexit__, so a click that never landed still
                # waited out the full event timeout — 47s — and the timeout
                # then replaced "the Click Here link was not clicked" with a
                # bare 'Timeout exceeded while waiting for event "page"',
                # pointing at the framework instead of at the selector.
                #
                # context.on() registers synchronously, so there is no window
                # in which a popup could be missed; the failure path returns
                # the moment the click reports it missed, and only the success
                # path waits.
                loop  = asyncio.get_running_loop()
                popup = loop.create_future()

                def _on_page(new: object) -> None:
                    if not popup.done():
                        popup.set_result(new)

                page.context.on("page", _on_page)
                try:
                    if not await pom.click_click_here():
                        return StepResult(
                            step=step, status="failed",
                            error="ti_open_new_window: the Click Here link was not "
                                  "clicked (the selector matches nothing, or the "
                                  "element is present but not interactable)",
                        )
                    new_page = await asyncio.wait_for(popup, timeout=15)
                except asyncio.TimeoutError:
                    return StepResult(
                        step=step, status="failed",
                        error="ti_open_new_window: the link was clicked but no new "
                              "window opened within 15s",
                    )
                finally:
                    page.context.remove_listener("page", _on_page)

                await new_page.wait_for_load_state("domcontentloaded")
                logger.info("ti_open_new_window ✓ — new window at %s", new_page.url)
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("ti_open_new_window failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        cls.register_actions(registry, cls.TiOpenNewWindowAction())
