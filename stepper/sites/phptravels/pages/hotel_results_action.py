"""
sites/phptravels/pages/hotel_results_action.py — Stepper glue for phpTravels hotel results.

Wraps HotelResultsPage into the named behavior "pt_select_hotel".

JSON usage:
  { "action": "pt_select_hotel" }
  { "action": "pt_select_hotel", "extra": { "hotel_name": "Burj Al Arab" } }

When hotel_name is provided, clicks the first result whose name matches exactly.
When omitted, clicks the first hotel on the page.
After this step the browser is on the hotel detail page.
The selected hotel name is stored in context output["selected_hotel"].
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PTHotelResultsPage(PageModule):
    site = "pt"

    class PTSelectHotelAction(GlueAction):
        """
        On the hotel results page: click a hotel by name (if provided) or
        click the first available hotel. Leaves the browser on the detail page.

        Optional extra keys:
          hotel_name — exact name to match; omit to pick the first result.

        JSON usage:
          { "action": "pt_select_hotel" }
        """
        action_name = "pt_select_hotel"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.phpTravels.config import load_settings
                from poms.phpTravels.pages.hotel_results_page import HotelResultsPage

                settings = load_settings()
                driver   = self._driver(page)
                results  = self._build_pom(HotelResultsPage, driver, settings.base_url,
                                           page=page, resolver=resolver)

                hotel_name = step.extra.get("hotel_name", "")

                if hotel_name:
                    clicked = await results.click_hotel_by_name(hotel_name)
                    if not clicked:
                        return StepResult(
                            step=step, status="failed",
                            error=f"pt_select_hotel: hotel '{hotel_name}' not found in results",
                        )
                    selected = hotel_name
                else:
                    selected = await results.click_first_hotel()
                    if not selected:
                        return StepResult(
                            step=step, status="failed",
                            error="pt_select_hotel: no hotels found on results page",
                        )

                logger.info("pt_select_hotel ✓ — selected: %s", selected)
                return StepResult(
                    step=step, status="passed",
                    output={"selected_hotel": selected},
                )

            except Exception as e:
                logger.error("pt_select_hotel failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.PTSelectHotelAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
