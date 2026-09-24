"""
phpTravels/pages/home_page.py — Pure POM for the phpTravels home / search page.

Single responsibility: selectors and raw interactions for the home search form.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class HomePage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        SUGGESTION_LIST     = ".tt-menu"
        NAV_LOGO            = ".navbar-brand"
        NAV_MY_ACCOUNT      = "a[href*='/account']"

        # Select-option targets (CSS strings — used with _select_option)
        HOTEL_ADULTS   = "#hotels select[name='adults']"
        HOTEL_CHILDREN = "#hotels select[name='children']"
        HOTEL_ROOMS    = "#hotels select[name='rooms']"
        FLIGHT_ADULTS  = "#flights select[name='adults']"

        # ── Interactive ───────────────────────────────────────────────────────
        TAB_HOTELS = Locator(
            role="link", name="Hotels",
            css="a[href*='#hotels']",
            description="Hotels tab",
        )
        TAB_FLIGHTS = Locator(
            role="link", name="Flights",
            css="a[href*='#flights']",
            description="Flights tab",
        )
        TAB_TOURS = Locator(
            role="link", name="Tours",
            css="a[href*='#tours']",
            description="Tours tab",
        )
        HOTEL_DESTINATION = Locator(
            placeholder="Destination",
            css="#hotels input.typeahead",
            description="hotel destination input",
        )
        #: A collection, so plain CSS and an index — not a Locator.
        #:
        #: It was a Locator going through _interact, and that could not work:
        #: a typeahead's whole purpose is to offer several matches, the cascade
        #: resolves exactly one element, and 2+ is ambiguity it refuses. Typing
        #: "Dubai" produced two suggestions, the deterministic phase fell
        #: through, the semantic phase could not match "first autocomplete
        #: suggestion" against the text "Dubai"/"Dubai Marina", and the step
        #: failed. It would only ever have worked when the query happened to
        #: have exactly one match. Same rule as SauceDemo's inventory list and
        #: Pathly's project cards — see pom-layer.md on collections.
        SUGGESTION_ITEM = ".tt-suggestion"
        HOTEL_CHECKIN = Locator(
            placeholder="Check In",
            css="#hotels input[name='checkin']",
            description="hotel check-in date",
        )
        HOTEL_CHECKOUT = Locator(
            placeholder="Check Out",
            css="#hotels input[name='checkout']",
            description="hotel check-out date",
        )
        HOTEL_SEARCH_BTN = Locator(
            role="button", name="Search",
            css="#hotels button[type='submit']",
            description="hotel search submit button",
        )
        FLIGHT_ORIGIN = Locator(
            placeholder="From",
            css="#flights input[name='from']",
            description="flight origin input",
        )
        FLIGHT_DESTINATION = Locator(
            placeholder="To",
            css="#flights input[name='to']",
            description="flight destination input",
        )
        FLIGHT_DEPART_DATE = Locator(
            placeholder="Departure Date",
            css="#flights input[name='departure_date']",
            description="flight departure date",
        )
        FLIGHT_RETURN_DATE = Locator(
            placeholder="Return Date",
            css="#flights input[name='return_date']",
            description="flight return date",
        )
        FLIGHT_SEARCH_BTN = Locator(
            role="button", name="Search",
            css="#flights button[type='submit']",
            description="flight search submit button",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.HOTEL_SEARCH_BTN.css, timeout=15_000
            )
        except Exception:
            pass

    # ── Tab navigation ────────────────────────────────────────────────────────

    async def select_hotels_tab(self) -> bool:
        return await self._interact(self.Locators.TAB_HOTELS, "click")

    async def select_flights_tab(self) -> bool:
        return await self._interact(self.Locators.TAB_FLIGHTS, "click")

    async def select_tours_tab(self) -> bool:
        return await self._interact(self.Locators.TAB_TOURS, "click")

    # ── Hotels form ───────────────────────────────────────────────────────────

    async def fill_hotel_destination(self, value: str) -> bool:
        if not await self._interact(self.Locators.HOTEL_DESTINATION, "fill", value=value):
            return False
        try:
            await self._driver.wait_for_selector(
                self.Locators.SUGGESTION_LIST, timeout=5_000
            )
        except Exception:
            pass
        return True

    async def select_first_hotel_suggestion(self) -> bool:
        """True if a suggestion was there to take; False if the menu was empty."""
        items = await self._driver.query_selector_all(self.Locators.SUGGESTION_ITEM)
        if not items:
            return False
        await items[0].click()
        return True

    async def fill_hotel_checkin(self, date: str) -> bool:
        return await self._interact(self.Locators.HOTEL_CHECKIN, "fill", value=date)

    async def fill_hotel_checkout(self, date: str) -> bool:
        return await self._interact(self.Locators.HOTEL_CHECKOUT, "fill", value=date)

    async def fill_hotel_adults(self, count: str) -> None:
        await self._select_option(self.Locators.HOTEL_ADULTS, count)

    async def submit_hotel_search(self) -> bool:
        if not await self._interact(self.Locators.HOTEL_SEARCH_BTN, "click"):
            return False
        await self._driver.wait_for_load_state("domcontentloaded")
        return True

    # ── Flights form ──────────────────────────────────────────────────────────

    async def fill_flight_origin(self, value: str) -> bool:
        return await self._interact(self.Locators.FLIGHT_ORIGIN, "fill", value=value)

    async def fill_flight_destination(self, value: str) -> bool:
        return await self._interact(self.Locators.FLIGHT_DESTINATION, "fill", value=value)

    async def fill_flight_depart_date(self, date: str) -> bool:
        return await self._interact(self.Locators.FLIGHT_DEPART_DATE, "fill", value=date)

    async def fill_flight_return_date(self, date: str) -> bool:
        return await self._interact(self.Locators.FLIGHT_RETURN_DATE, "fill", value=date)

    async def submit_flight_search(self) -> bool:
        if not await self._interact(self.Locators.FLIGHT_SEARCH_BTN, "click"):
            return False
        await self._driver.wait_for_load_state("domcontentloaded")
        return True
