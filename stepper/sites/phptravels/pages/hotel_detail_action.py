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

from stepper.engine.browser.human_behaviour import HumanBehaviour
from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

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
            behaviour: HumanBehaviour | None = None,
        ) -> StepResult:
            try:
                from poms.phpTravels.config import load_settings
                from poms.phpTravels.pages.hotel_detail_page import HotelDetailPage

                settings = load_settings()
                driver   = self._driver(page)
                detail   = self._build_pom(HotelDetailPage, driver, settings.base_url,
                                           page=page, resolver=resolver, behaviour=behaviour)

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

                if not await detail.fill_checkin_date(checkin):
                    return StepResult(
                        step=step, status="failed",
                        error="pt_book_hotel: fill_checkin_date() did not act — the selector "
                              "matched nothing, or the element was present but "
                              "not interactable",
                    )
                if not await detail.fill_checkout_date(checkout):
                    return StepResult(
                        step=step, status="failed",
                        error="pt_book_hotel: fill_checkout_date() did not act — the selector "
                              "matched nothing, or the element was present but "
                              "not interactable",
                    )
                await detail.fill_adults(adults)
                await detail.fill_children(children)
                if not await detail.submit_booking():
                    return StepResult(
                        step=step, status="failed",
                        error="pt_book_hotel: submit_booking() did not act — the selector "
                              "matched nothing, or the element was present but "
                              "not interactable",
                    )

                booking_ref = await detail.get_booking_reference()
                confirmed   = await detail.is_booking_confirmed()

                # The submit landed; that is not the same as the booking being
                # taken. Neither a confirmation banner nor a reference means the
                # one fact this step exists to establish is absent.
                if not confirmed and not booking_ref:
                    return StepResult(
                        step=step, status="failed",
                        error="pt_book_hotel: the booking form was submitted but the "
                              "page shows neither a confirmation nor a booking "
                              "reference — the booking was not taken",
                    )

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
        cls.register_actions(registry, cls.PTBookHotelAction())
