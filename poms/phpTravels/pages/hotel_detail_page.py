"""
phpTravels/pages/hotel_detail_page.py — Pure POM for a phpTravels hotel detail page.

Single responsibility: selectors and raw interactions for viewing and booking
a single hotel.
"""
from __future__ import annotations
import logging

from poms.phpTravels.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class HotelDetailPage(BasePage):

    class Locators:
        # ── Read-only ─────────────────────────────────────────────────────────
        HOTEL_NAME     = "h1.hotel-name, h2.hotel-title, .hotel_title h2"
        HOTEL_PRICE    = ".price strong, .amount, .rate"
        HOTEL_STARS    = ".fa-star"
        HOTEL_ADDRESS  = ".hotel-address, address"
        HOTEL_DESC     = ".hotel-description, .description p"
        ROOM_ROW       = ".room-type, .room-row"
        ROOM_NAME      = ".room-name, td:first-child"
        ROOM_PRICE     = ".room-price, td.price"
        ROOM_BOOK_BTN  = "a.book-now, button.book-room"
        CONFIRM_REF    = ".booking-ref, .confirmation-number, #booking_ref"
        CONFIRM_HEADER = ".booking-confirmed, .success-header"

        # Select-option targets
        ADULTS_SELECT   = "select[name='adults']"
        CHILDREN_SELECT = "select[name='children']"

        # ── Interactive ───────────────────────────────────────────────────────
        CHECKIN_DATE = Locator(
            placeholder="Check In",
            id="checkin",
            css="input[name='checkin']",
            description="check-in date field",
        )
        CHECKOUT_DATE = Locator(
            placeholder="Check Out",
            id="checkout",
            css="input[name='checkout']",
            description="check-out date field",
        )
        BOOK_NOW = Locator(
            role="button", name="Book Now",
            id="book_now",
            css="button[type='submit'].book-now",
            description="book now submit button",
        )

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
        el = await self._driver.query_selector(self.Locators.HOTEL_PRICE)
        return (await el.inner_text()).strip() if el else ""

    async def get_star_rating(self) -> int:
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
        await self._interact(self.Locators.CHECKIN_DATE, "fill", value=date)

    async def fill_checkout_date(self, date: str) -> None:
        await self._interact(self.Locators.CHECKOUT_DATE, "fill", value=date)

    async def fill_adults(self, count: str) -> None:
        await self._select_option(self.Locators.ADULTS_SELECT, count)

    async def fill_children(self, count: str) -> None:
        await self._select_option(self.Locators.CHILDREN_SELECT, count)

    async def submit_booking(self) -> None:
        await self._interact(self.Locators.BOOK_NOW, "click")
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
