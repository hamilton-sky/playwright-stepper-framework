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
        await self._driver.click(self.Locators.TAB_HOTELS)

    async def select_flights_tab(self) -> None:
        await self._driver.click(self.Locators.TAB_FLIGHTS)

    async def select_tours_tab(self) -> None:
        await self._driver.click(self.Locators.TAB_TOURS)

    # ── Hotels form ───────────────────────────────────────────────────────────

    async def fill_hotel_destination(self, value: str) -> None:
        """Type into the destination autocomplete and wait for suggestions."""
        await self._driver.fill(self.Locators.HOTEL_DESTINATION, value)
        try:
            await self._driver.wait_for_selector(
                self.Locators.SUGGESTION_LIST, timeout=5_000
            )
        except Exception:
            pass  # suggestions may not appear for all inputs

    async def select_first_hotel_suggestion(self) -> None:
        """Click the first suggestion in the autocomplete dropdown."""
        await self._driver.click(self.Locators.SUGGESTION_ITEM)

    async def fill_hotel_checkin(self, date: str) -> None:
        """date: 'DD-MM-YYYY' or whatever format the site expects."""
        await self._driver.fill(self.Locators.HOTEL_CHECKIN, date)

    async def fill_hotel_checkout(self, date: str) -> None:
        await self._driver.fill(self.Locators.HOTEL_CHECKOUT, date)

    async def fill_hotel_adults(self, count: str) -> None:
        page = self._page
        if page:
            await page.select_option(self.Locators.HOTEL_ADULTS, count)
        else:
            await self._driver.evaluate(
                f"document.querySelector('{self.Locators.HOTEL_ADULTS}').value = '{count}';"
                f"document.querySelector('{self.Locators.HOTEL_ADULTS}').dispatchEvent(new Event('change'));"
            )

    async def submit_hotel_search(self) -> None:
        await self._driver.click(self.Locators.HOTEL_SEARCH_BTN)
        await self._driver.wait_for_load_state("domcontentloaded")

    # ── Flights form ──────────────────────────────────────────────────────────

    async def fill_flight_origin(self, value: str) -> None:
        await self._driver.fill(self.Locators.FLIGHT_ORIGIN, value)

    async def fill_flight_destination(self, value: str) -> None:
        await self._driver.fill(self.Locators.FLIGHT_DESTINATION, value)

    async def fill_flight_depart_date(self, date: str) -> None:
        await self._driver.fill(self.Locators.FLIGHT_DEPART_DATE, date)

    async def fill_flight_return_date(self, date: str) -> None:
        await self._driver.fill(self.Locators.FLIGHT_RETURN_DATE, date)

    async def submit_flight_search(self) -> None:
        await self._driver.click(self.Locators.FLIGHT_SEARCH_BTN)
        await self._driver.wait_for_load_state("domcontentloaded")
