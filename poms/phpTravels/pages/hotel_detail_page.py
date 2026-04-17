"""
phpTravels/pages/hotel_detail_page.py — Pure POM for a phpTravels hotel detail page.

Single responsibility: selectors and raw interactions for viewing and booking
a single hotel.

Exposed interactions:
  - read hotel name, description, price
  - fill booking form (dates, guests)
  - submit booking
  - read confirmation reference

No flow logic, no assertions.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage

logger = logging.getLogger(__name__)


class HotelDetailPage(BasePage):

    class Locators:
        """All hotel-detail selectors. Never duplicated elsewhere."""
        # ── Hotel info ────────────────────────────────────────────────────────
        HOTEL_NAME     = "h1.hotel-name, h2.hotel-title, .hotel_title h2"
        HOTEL_PRICE    = ".price strong, .amount, .rate"
        HOTEL_STARS    = ".fa-star"
        HOTEL_ADDRESS  = ".hotel-address, address"
        HOTEL_DESC     = ".hotel-description, .description p"

        # ── Room / rate selection ─────────────────────────────────────────────
        ROOM_ROW       = ".room-type, .room-row"
        ROOM_NAME      = ".room-name, td:first-child"
        ROOM_PRICE     = ".room-price, td.price"
        ROOM_BOOK_BTN  = "a.book-now, button.book-room"

        # ── Booking panel — plain strings for select_option ──────────────────
        CHECKIN_DATE    = "input[name='checkin']"
        CHECKOUT_DATE   = "input[name='checkout']"
        ADULTS_SELECT   = "select[name='adults']"
        CHILDREN_SELECT = "select[name='children']"
        BOOK_NOW_BTN    = "button[type='submit'].book-now"

        # ── Interactive cfg lists ─────────────────────────────────────────────
        CHECKIN_DATE_CFG = [
            {"placeholder": "Check In",              "priority": 10},
            {"id":          "checkin",               "priority": 20},
            {"css":         "input[name='checkin']", "priority": 30},
        ]
        CHECKOUT_DATE_CFG = [
            {"placeholder": "Check Out",              "priority": 10},
            {"id":          "checkout",               "priority": 20},
            {"css":         "input[name='checkout']", "priority": 30},
        ]
        BOOK_NOW_BTN_CFG = [
            {"role": "button", "name": "Book Now",           "priority": 10},
            {"id":   "book_now",                             "priority": 20},
            {"css":  "button[type='submit'].book-now",       "priority": 30},
        ]

        # ── Confirmation ──────────────────────────────────────────────────────
        CONFIRM_REF    = ".booking-ref, .confirmation-number, #booking_ref"
        CONFIRM_HEADER = ".booking-confirmed, .success-header"

    def __init__(self, driver, base_url: str, hotel_slug: str | None = None,
                 page=None, resolver=None):
        super().__init__(driver, base_url, page, resolver)
        self._hotel_slug = hotel_slug

    @property
    def url(self) -> str:
        if self._hotel_slug:
            return f"{self.base_url}/hotels/{self._hotel_slug}"
        return f"{self.base_url}/hotels"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.HOTEL_NAME, timeout=15_000
            )
        except Exception:
            pass

    # ── Hotel info reads ──────────────────────────────────────────────────────

    async def get_name(self) -> str:
        el = await self._driver.query_selector(self.Locators.HOTEL_NAME)
        return (await el.inner_text()).strip() if el else ""

    async def get_price(self) -> str:
        """Return the price as raw text (currency varies by region)."""
        el = await self._driver.query_selector(self.Locators.HOTEL_PRICE)
        return (await el.inner_text()).strip() if el else ""

    async def get_star_rating(self) -> int:
        """Count visible star icons."""
        try:
            stars = await self._driver.query_selector_all(self.Locators.HOTEL_STARS)
            return len(stars)
        except Exception:
            return 0

    async def get_description(self) -> str:
        el = await self._driver.query_selector(self.Locators.HOTEL_DESC)
        return (await el.inner_text()).strip() if el else ""

    # ── Booking form ──────────────────────────────────────────────────────────

    async def fill_checkin_date(self, date: str) -> None:
        """date: format expected by the site (e.g. '25-04-2026')."""
        await self._resolve_and_fill_any(self.Locators.CHECKIN_DATE_CFG, date)

    async def fill_checkout_date(self, date: str) -> None:
        await self._resolve_and_fill_any(self.Locators.CHECKOUT_DATE_CFG, date)

    async def fill_adults(self, count: str) -> None:
        await self._select_option(self.Locators.ADULTS_SELECT, count)

    async def fill_children(self, count: str) -> None:
        await self._select_option(self.Locators.CHILDREN_SELECT, count)

    async def submit_booking(self) -> None:
        await self._resolve_and_click_any(self.Locators.BOOK_NOW_BTN_CFG)
        await self._driver.wait_for_load_state("domcontentloaded")
        logger.info("Booking submitted for hotel: %s", self._hotel_slug)

    # ── Confirmation reads ────────────────────────────────────────────────────

    async def get_booking_reference(self) -> str | None:
        try:
            el = await self._driver.query_selector(self.Locators.CONFIRM_REF)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return None

    async def is_booking_confirmed(self) -> bool:
        try:
            return await self._driver.locator_count(self.Locators.CONFIRM_HEADER) > 0
        except Exception:
            return False
