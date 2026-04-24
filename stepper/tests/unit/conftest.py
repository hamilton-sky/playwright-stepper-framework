import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_stepper_dir = Path(__file__).resolve().parent.parent.parent   # stepper/
_repo_root   = _stepper_dir.parent
for _p in (_repo_root, _stepper_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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
