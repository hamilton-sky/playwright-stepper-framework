"""ti/pages/base_page.py — Base class for all the-internet pure POMs."""
from __future__ import annotations
import logging
from poms.shared.base_page import BasePage as SharedBasePage

logger = logging.getLogger(__name__)


class BasePage(SharedBasePage):
    """Base for all the-internet page objects."""
