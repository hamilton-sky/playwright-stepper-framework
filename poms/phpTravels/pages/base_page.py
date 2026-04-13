"""
phpTravels/pages/base_page.py — Base class for all phpTravels pure POMs.

Extends poms.shared.base_page.BasePage.
The resolver cascade is available if the glue layer injects page + resolver.

No flow logic. No credentials. No assertions.
The glue layer (stepper/sites/phptravels/) owns flows.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage as SharedBasePage

logger = logging.getLogger(__name__)


class BasePage(SharedBasePage):
    """
    Base for all phpTravels page objects.

    Subclasses define:
      - url property
      - wait_for_ready() override (optional)
      - domain methods (fill_*, click_*, get_*, is_*)
    """
    # base_url is stripped by SharedBasePage.__init__
