"""
saucedemo/pages/base_page.py — Base class for all SauceDemo pure POMs.

Extends poms.shared.base_page.BasePage.
SauceDemo uses clean data-test attributes so the full resolver cascade
is rarely needed, but the helpers are available if the glue layer injects
a page + resolver.

No flow logic. No credentials. No assertions.
The glue layer (stepper/sites/saucedemo/) owns flows.
"""
from __future__ import annotations
import logging

from poms.shared.base_page import BasePage as SharedBasePage

logger = logging.getLogger(__name__)


class BasePage(SharedBasePage):
    """
    Base for all SauceDemo page objects.

    Subclasses define:
      - url property
      - wait_for_ready() override (optional)
      - domain methods (fill_*, click_*, get_*, is_*)
    """
    # base_url is stripped by SharedBasePage.__init__
