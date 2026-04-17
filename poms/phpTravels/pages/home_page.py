"""
phpTravels/pages/home_page.py — Pure POM for the phpTravels home / search page.

Single responsibility: selectors and raw interactions for the home search form.

The form supports multiple service tabs (Hotels, Flights, Tours, etc.).
Each tab has its own search inputs. This POM owns all of them — switching
tabs is a single click, not a navigation event.

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class HomePage(BasePage):

    class Locators:
        """All home-page selectors. Never duplicated elsewhere."""

        # ── Service tabs ─────────────────────────────────────────────────────
        # Tab links — clicking them switches the search form panel
        TAB_HOTELS  = "a[href*='#hotels']"
        TAB_FLIGHTS = "a[href*='#flights']"
        TAB_TOURS   = "a[href*='#tours']"
        TAB_CARS    = "a[href*='#cars']"

        # ── Hotels search form ────────────────────────────────────────────────
        # Plain strings — used for wait_for_selector and select_option
        HOTEL_DESTINATION   = "#hotels input.typeahead"
        HOTEL_CHECKIN       = "#hotels input[name='checkin']"
        HOTEL_CHECKOUT      = "#hotels input[name='checkout']"
        HOTEL_ADULTS        = "#hotels select[name='adults']"
        HOTEL_CHILDREN      = "#hotels select[name='children']"
        HOTEL_ROOMS         = "#hotels select[name='rooms']"
        HOTEL_SEARCH_BTN    = "#hotels button[type='submit']"

        # ── Flights search form ───────────────────────────────────────────────
        FLIGHT_ORIGIN       = "#flights input[name='from']"
        FLIGHT_DESTINATION  = "#flights input[name='to']"
        FLIGHT_DEPART_DATE  = "#flights input[name='departure_date']"
        FLIGHT_RETURN_DATE  = "#flights input[name='return_date']"
        FLIGHT_ADULTS       = "#flights select[name='adults']"
        FLIGHT_SEARCH_BTN   = "#flights button[type='submit']"

        # ── Tours search form ─────────────────────────────────────────────────
        TOUR_DESTINATION    = "#tours input.typeahead"
        TOUR_DATE           = "#tours input[name='date']"
        TOUR_ADULTS         = "#tours select[name='adults']"
        TOUR_SEARCH_BTN     = "#tours button[type='submit']"

        # ── Typeahead suggestion list (shared across tabs) ────────────────────
        SUGGESTION_ITEM     = ".tt-suggestion"
        SUGGESTION_LIST     = ".tt-menu"

        # ── Nav bar ───────────────────────────────────────────────────────────
        NAV_LOGO            = ".navbar-brand"
        NAV_MY_ACCOUNT      = "a[href*='/account']"

        # ── Interactive cfg lists ─────────────────────────────────────────────
        TAB_HOTELS_CFG = [
            {"role": "link", "name": "Hotels",       "priority": 10},
            {"css":  "a[href*='#hotels']",            "priority": 20},
        ]
        TAB_FLIGHTS_CFG = [
            {"role": "link", "name": "Flights",      "priority": 10},
            {"css":  "a[href*='#flights']",           "priority": 20},
        ]
        TAB_TOURS_CFG = [
            {"role": "link", "name": "Tours",        "priority": 10},
            {"css":  "a[href*='#tours']",             "priority": 20},
        ]
        HOTEL_DESTINATION_CFG = [
            {"placeholder": "Destination",              "priority": 10},
            {"css":         "#hotels input.typeahead",  "priority": 20},
        ]
        SUGGESTION_ITEM_CFG = [
            {"css": ".tt-suggestion", "priority": 10},
        ]
        HOTEL_CHECKIN_CFG = [
            {"placeholder": "Check In",                      "priority": 10},
            {"css":         "#hotels input[name='checkin']", "priority": 20},
        ]
        HOTEL_CHECKOUT_CFG = [
            {"placeholder": "Check Out",                      "priority": 10},
            {"css":         "#hotels input[name='checkout']", "priority": 20},
        ]
        HOTEL_SEARCH_BTN_CFG = [
            {"role": "button", "name": "Search",         "priority": 10},
            {"css":  "#hotels button[type='submit']",    "priority": 20},
        ]
        FLIGHT_ORIGIN_CFG = [
            {"placeholder": "From",                         "priority": 10},
            {"css":         "#flights input[name='from']",  "priority": 20},
        ]
        FLIGHT_DESTINATION_CFG = [
            {"placeholder": "To",                          "priority": 10},
            {"css":         "#flights input[name='to']",   "priority": 20},
        ]
        FLIGHT_DEPART_DATE_CFG = [
            {"placeholder": "Departure Date",                        "priority": 10},
            {"css":         "#flights input[name='departure_date']", "priority": 20},
        ]
        FLIGHT_RETURN_DATE_CFG = [
            {"placeholder": "Return Date",                          "priority": 10},
            {"css":         "#flights input[name='return_date']",   "priority": 20},
        ]
        FLIGHT_SEARCH_BTN_CFG = [
            {"role": "button", "name": "Search",          "priority": 10},
            {"css":  "#flights button[type='submit']",    "priority": 20},
        ]

    @property
    def url(self) -> str:
        return f"{self.base_url}/"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.HOTEL_SEARCH_BTN, timeout=15_000
            )
        except Exception:
            pass

    # ── Tab navigation ────────────────────────────────────────────────────────

    async def select_hotels_tab(self) -> None:
        await self._resolve_and_click_any(self.Locators.TAB_HOTELS_CFG)

    async def select_flights_tab(self) -> None:
        await self._resolve_and_click_any(self.Locators.TAB_FLIGHTS_CFG)

    async def select_tours_tab(self) -> None:
        await self._resolve_and_click_any(self.Locators.TAB_TOURS_CFG)

    # ── Hotels form ───────────────────────────────────────────────────────────

    async def fill_hotel_destination(self, value: str) -> None:
        """Type into the destination autocomplete and wait for suggestions."""
        await self._resolve_and_fill_any(self.Locators.HOTEL_DESTINATION_CFG, value)
        try:
            await self._driver.wait_for_selector(
                self.Locators.SUGGESTION_LIST, timeout=5_000
            )
        except Exception:
            pass  # suggestions may not appear for all inputs

    async def select_first_hotel_suggestion(self) -> None:
        """Click the first suggestion in the autocomplete dropdown."""
        await self._resolve_and_click_any(self.Locators.SUGGESTION_ITEM_CFG)

    async def fill_hotel_checkin(self, date: str) -> None:
        """date: 'DD-MM-YYYY' or whatever format the site expects."""
        await self._resolve_and_fill_any(self.Locators.HOTEL_CHECKIN_CFG, date)

    async def fill_hotel_checkout(self, date: str) -> None:
        await self._resolve_and_fill_any(self.Locators.HOTEL_CHECKOUT_CFG, date)

    async def fill_hotel_adults(self, count: str) -> None:
        await self._select_option(self.Locators.HOTEL_ADULTS, count)

    async def submit_hotel_search(self) -> None:
        await self._resolve_and_click_any(self.Locators.HOTEL_SEARCH_BTN_CFG)
        await self._driver.wait_for_load_state("domcontentloaded")

    # ── Flights form ──────────────────────────────────────────────────────────

    async def fill_flight_origin(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.FLIGHT_ORIGIN_CFG, value)

    async def fill_flight_destination(self, value: str) -> None:
        await self._resolve_and_fill_any(self.Locators.FLIGHT_DESTINATION_CFG, value)

    async def fill_flight_depart_date(self, date: str) -> None:
        await self._resolve_and_fill_any(self.Locators.FLIGHT_DEPART_DATE_CFG, date)

    async def fill_flight_return_date(self, date: str) -> None:
        await self._resolve_and_fill_any(self.Locators.FLIGHT_RETURN_DATE_CFG, date)

    async def submit_flight_search(self) -> None:
        await self._resolve_and_click_any(self.Locators.FLIGHT_SEARCH_BTN_CFG)
        await self._driver.wait_for_load_state("domcontentloaded")
