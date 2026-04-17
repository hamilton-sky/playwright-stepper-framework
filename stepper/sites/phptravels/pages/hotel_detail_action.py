"""
sites/phptravels/pages/hotel_detail_action.py — Stepper glue for phpTravels hotel booking.

Wraps HotelDetailPage into the named behavior "pt_book_hotel".

JSON usage:
  {
    "action": "pt_book_hotel",
    "extra": {
      "checkin":  "25-05-2026",
      "checkout": "27-05-2026",
      "adults":   "2",
      "children": "0"
    }
  }

Assumes the browser is already on the hotel detail page (after pt_select_hotel).
Stores booking_reference in context output when the confirmation is detected.
"""
from __future__ import annotations
import logging

from engine.interfaces import StepConfig, StepResult, ExecutionContext
from engine.pages.base_page_module import PageModule
from engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class PTHotelDetailPage(PageModule):
    site = "pt"

    class PTBookHotelAction(GlueAction):
        """
        On the hotel detail page: fill the booking form and submit.

        Required extra keys: checkin, checkout.
        Optional extra keys: adults (default "2"), children (default "0").

        JSON usage:
          { "action": "pt_book_hotel", "extra": { "checkin": "25-05-2026",
            "checkout": "27-05-2026" } }
        """
        action_name = "pt_book_hotel"

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
        ) -> StepResult:
            try:
                from poms.phpTravels.config import load_settings
                from poms.phpTravels.pages.hotel_detail_page import HotelDetailPage

                settings = load_settings()
                driver   = self._driver(page)
                detail   = self._build_pom(HotelDetailPage, driver, settings.base_url,
                                           page=page, resolver=resolver)

                checkin  = step.extra.get("checkin", "")
                checkout = step.extra.get("checkout", "")
                adults   = str(step.extra.get("adults", "2"))
                children = str(step.extra.get("children", "0"))

                if not checkin or not checkout:
                    return StepResult(
                        step=step, status="failed",
                        error="pt_book_hotel: extra.checkin and extra.checkout are required",
                    )

                hotel_name = await detail.get_name()
                logger.info(
                    "pt_book_hotel — booking '%s'  checkin=%s checkout=%s adults=%s children=%s",
                    hotel_name, checkin, checkout, adults, children,
                )

                await detail.fill_checkin_date(checkin)
                await detail.fill_checkout_date(checkout)
                await detail.fill_adults(adults)
                await detail.fill_children(children)
                await detail.submit_booking()

                booking_ref = await detail.get_booking_reference()
                confirmed   = await detail.is_booking_confirmed()

                if not confirmed and not booking_ref:
                    logger.warning("pt_book_hotel — no confirmation detected after submit")

                logger.info(
                    "pt_book_hotel ✓ — ref=%s confirmed=%s",
                    booking_ref or "n/a", confirmed,
                )
                return StepResult(
                    step=step, status="passed",
                    output={"booking_reference": booking_ref, "confirmed": confirmed},
                )

            except Exception as e:
                logger.error("pt_book_hotel failed: %s", e)
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action = cls.PTBookHotelAction()
        registry.register(action)
        logger.debug("Registered action: %s", action.action_name)
