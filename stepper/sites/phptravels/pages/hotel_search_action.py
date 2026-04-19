"""
sites/phptravels/pages/hotel_search_action.py — Stepper glue for phpTravels hotel search.

Wraps HomePage into the named behavior "pt_search_hotels".

JSON usage:
  {
    "action": "pt_search_hotels",
    "extra": {
      "destination": "Dubai",
      "checkin":     "25-05-2026",
      "checkout":    "27-05-2026",
      "adults":      "2"
    }
  }

All params are required except "adults" (defaults to "2").
After this step the browser is on the hotel results page.
"""
from __future__ import annotations
import logging

from engine.browser.human_behaviour import HumanBehaviour
from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PTHotelSearchPage(PageModule):
    site = "pt"

    class PTSearchHotelsAction(GlueAction):
        """
        Open the phpTravels home page, select the Hotels tab, fill the search
        form, and submit. Leaves the browser on the hotel results page.

        Required extra keys: destination, checkin, checkout.
        Optional extra keys: adults (default "2").

        JSON usage:
          { "action": "pt_search_hotels", "extra": { "destination": "Dubai",
            "checkin": "25-05-2026", "checkout": "27-05-2026" } }
        """
        action_name = "pt_search_hotels"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
            behaviour: HumanBehaviour,
        ) -> StepResult:
            try:
                from poms.phpTravels.config import load_settings
                from poms.phpTravels.pages.home_page import HomePage

                settings = load_settings()
                driver   = self._driver(page)
                home     = self._build_pom(HomePage, driver, settings.base_url,
                                           page=page, resolver=resolver, behaviour=behaviour)

                destination = step.extra.get("destination", "")
                checkin     = step.extra.get("checkin", "")
                checkout    = step.extra.get("checkout", "")
                adults      = str(step.extra.get("adults", "2"))

                if not destination or not checkin or not checkout:
                    return StepResult(
                        step=step, status="failed",
                        error="pt_search_hotels: extra.destination, checkin, and checkout are required",
                    )

                logger.info(
                    "pt_search_hotels — destination=%r checkin=%s checkout=%s adults=%s",
                    destination, checkin, checkout, adults,
                )

                await home.open()
                await home.select_hotels_tab()
                await home.fill_hotel_destination(destination)
                await home.select_first_hotel_suggestion()
                await home.fill_hotel_checkin(checkin)
                await home.fill_hotel_checkout(checkout)
                await home.fill_hotel_adults(adults)
                await home.submit_hotel_search()

                logger.info("pt_search_hotels ✓ — on results page")
                return StepResult(step=step, status="passed")

            except Exception as e:
                logger.error("pt_search_hotels failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.PTSearchHotelsAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
