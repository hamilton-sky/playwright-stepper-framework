import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# `stepper` and `poms` resolve through the installed package
# (`pip install -e .`). This one entry lets the suite also run straight from a
# checkout with nothing installed. The second entry that used to sit here
# pointed at stepper/, so that `engine`, `main` and `cli` resolved as top-level
# modules; everything is under `stepper.*` now, so it is gone.
_stepper_dir = Path(__file__).resolve().parent.parent.parent   # stepper/
_repo_root   = _stepper_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


@pytest.fixture
def step_factory():
    def _make(action="click", description="click submit", element=None):
        return SimpleNamespace(
            action=action,
            description=description,
            element=element or {"css": ".btn"},
        )
    return _make


@pytest.fixture
def mock_page():
    """Playwright Page mock — every locator method returns an AsyncMock with .all() → []."""
    page = MagicMock()
    for method in ("get_by_text", "get_by_role", "get_by_placeholder", "get_by_label", "locator"):
        loc = MagicMock()
        loc.all = AsyncMock(return_value=[])
        getattr(page, method).return_value = loc
    return page
