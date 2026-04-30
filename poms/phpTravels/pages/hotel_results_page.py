"""
phpTravels/pages/hotel_results_page.py — Pure POM for the phpTravels hotel results page.

Single responsibility: selectors and raw interactions for the hotel search results.

Exposed interactions:
  - collect all visible hotel cards (name, price, rating)
  - filter by price or rating
  - click through to a hotel detail page

No flow logic, no assertions.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from poms.phpTravels.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


@dataclass
class HotelSummary:
    """Value object — one hotel card as read from the results page."""
    name:          str
    price_per_night: float | None
    star_rating:   int | None
    detail_url:    str | None


class HotelResultsPage(BasePage):

    class Locators:
        """All hotel-results selectors. Never duplicated elsewhere."""
        # ── Result cards ──────────────────────────────────────────────────────
        HOTEL_CARD      = ".col-md-12.hotel-listing"
        HOTEL_NAME      = "h4.card-title a, h3.card-title a"
        HOTEL_PRICE     = ".price strong, .amount"
        HOTEL_STARS     = ".fa-star"          # count visible star icons
        HOTEL_BOOK_BTN = Locator(
            role="link",
            css="a.btn-primary",
            css_fallbacks=["a[href*='hotel/']"],
            description="hotel book/detail link",
        )

        # ── Pagination ────────────────────────────────────────────────────────
        NEXT_PAGE = Locator(
            css="a[rel='next']",
            css_fallbacks=[".pagination .next a"],
            description="pagination next link",
        )

        # ── Filter sidebar ────────────────────────────────────────────────────
        FILTER_STARS    = ".star-filter input[type='checkbox']"
        FILTER_APPLY    = "button[data-filter='apply'], .apply-filter"

        # ── Loading indicator ─────────────────────────────────────────────────
        LOADING_SPINNER = ".loading, .spinner"

    @property
    def url(self) -> str:
        return f"{self.base_url}/hotels"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.HOTEL_CARD, timeout=20_000
            )
        except Exception:
            pass

    # ── Hotel reads ───────────────────────────────────────────────────────────

    async def get_hotels(self) -> list[HotelSummary]:
        """Return a summary for every visible hotel card on the current page."""
        cards  = await self._driver.query_selector_all(self.Locators.HOTEL_CARD)
        result = []
        for card in cards:
            name_el  = await card.query_selector(self.Locators.HOTEL_NAME)
            price_el = await card.query_selector(self.Locators.HOTEL_PRICE)
            star_els = await card.query_selector_all(self.Locators.HOTEL_STARS)
            link_el = None
            for css in self.Locators.HOTEL_BOOK_BTN.css_candidates():
                link_el = await card.query_selector(css)
                if link_el:
                    break

            name = (await name_el.inner_text()).strip() if name_el else ""

            price: float | None = None
            if price_el:
                raw = (await price_el.inner_text()).strip()
                # strip currency symbols and commas, then parse
                cleaned = "".join(c for c in raw if c.isdigit() or c == ".")
                try:
                    price = float(cleaned)
                except ValueError:
                    logger.warning("Could not parse hotel price: %r", raw)

            stars: int | None = len(star_els) if star_els else None

            href: str | None = None
            if link_el:
                href = await link_el.get_attribute("href")
                if href and not href.startswith("http"):
                    href = self.base_url + href

            result.append(HotelSummary(
                name=name,
                price_per_night=price,
                star_rating=stars,
                detail_url=href,
            ))
        return result

    async def get_hotel_count(self) -> int:
        cards = await self._driver.query_selector_all(self.Locators.HOTEL_CARD)
        return len(cards)

    # ── Navigation ────────────────────────────────────────────────────────────

    async def click_hotel_by_name(self, name: str) -> bool:
        """
        Click the first result whose name matches exactly.
        Returns True if clicked, False if not found.
        """
        cards = await self._driver.query_selector_all(self.Locators.HOTEL_CARD)
        for card in cards:
            name_el = await card.query_selector(self.Locators.HOTEL_NAME)
            if not name_el:
                continue
            if (await name_el.inner_text()).strip() == name:
                await name_el.click()
                await self._driver.wait_for_load_state("domcontentloaded")
                logger.info("Clicked hotel: %s", name)
                return True
        logger.warning("Hotel not found in results: %s", name)
        return False

    async def click_first_hotel(self) -> str | None:
        """
        Click the first hotel card and return its name.
        Returns None if no cards are present.
        """
        cards = await self._driver.query_selector_all(self.Locators.HOTEL_CARD)
        if not cards:
            return None
        name_el = await cards[0].query_selector(self.Locators.HOTEL_NAME)
        name = (await name_el.inner_text()).strip() if name_el else ""
        clicked = await self._interact(self.Locators.HOTEL_BOOK_BTN, "click")
        if clicked:
            await self._driver.wait_for_load_state("domcontentloaded")
            logger.info("Clicked first hotel: %s", name)
        return name

    async def go_to_next_page(self) -> bool:
        """
        Click the pagination next link.
        Returns True if the link existed and was clicked, False if last page.
        """
        clicked = await self._interact(self.Locators.NEXT_PAGE, "click")
        if clicked:
            await self._driver.wait_for_load_state("domcontentloaded")
        return clicked
