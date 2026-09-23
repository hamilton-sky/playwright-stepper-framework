"""ti/pages/hovers_page.py — Pure POM for the-internet hovers page."""
from __future__ import annotations
import logging
from poms.ti.pages.base_page import BasePage
from poms.shared.locator import Locator

logger = logging.getLogger(__name__)


class HoversPage(BasePage):

    class Locators:
        # nth-of-type, not nth-child. The generator wrote
        # `.figure:nth-child(1) img`, which reads as "the first .figure" and is
        # not: :nth-child(1) means "is the first child of its parent AND is a
        # .figure", and the-internet puts an <h3> and a <br> ahead of them —
        # the figures are children 3, 4 and 5. It matched 0 elements, so the
        # hover never fired, .figcaption stayed display:none, and the click on
        # the revealed link could not land. Same family as the checkbox
        # selector in checkboxes_page.py: plausible CSS that matches nothing.
        USER_AVATAR_1 = Locator(
            role="img", name="User Avatar",
            css=".figure:nth-of-type(1) img",
            description="first user avatar image (hover to reveal profile link)",
        )
        VIEW_PROFILE_1 = Locator(
            role="link", name="View profile",
            css="a[href='/users/1']",
            description="view profile link for user 1 (visible after hover)",
        )

    @property
    def url(self) -> str:
        return f"{self.base_url}/hovers"

    async def wait_for_ready(self) -> None:
        try:
            await self._driver.wait_for_selector(
                self.Locators.USER_AVATAR_1.css, timeout=15_000
            )
        except Exception:
            pass

    async def hover_user_avatar_1(self) -> bool:
        """
        True if the avatar was there to hover. `query_selector` returns None
        for a selector that matches nothing, and the old `if el:` turned that
        into a silent no-op — which is how the wrong selector above survived.
        """
        el = await self._driver.query_selector(self.Locators.USER_AVATAR_1.css)
        if not el:
            return False
        await el.hover()
        return True

    async def click_view_profile_1(self) -> bool:
        return await self._interact(self.Locators.VIEW_PROFILE_1, "click")
