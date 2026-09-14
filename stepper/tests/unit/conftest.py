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


@pytest.fixture(autouse=True)
def no_embedding_model_loads(monkeypatch):
    """
    Fail loudly if a unit test constructs a real SemanticResolver.

    Its __init__ loads an embedding model. That used to be free: an 87MB copy
    was committed to the repo, so it came off local disk. The weights are a
    download cache now, so the same constructor reaches for the hub — turning a
    3-second offline suite into a ~90MB download, or a failure on a machine with
    no network.

    Nothing in the unit suite legitimately needs the real thing; tests that care
    about scoring inject a stub. The guard is here rather than in each test file
    because the expensive call is three frames down from anything a test writes
    directly — DOMSnapshotCascade._get_semantic() and ElementResolver.__init__
    both build one without being asked.

    Integration tests do not use this conftest and load the model normally.
    """
    def _refuse(self, *a, **kw):
        raise AssertionError(
            "A unit test constructed a real SemanticResolver, which loads an "
            "embedding model and would download ~90MB.\n"
            "Inject a stub instead, e.g.:\n"
            "    monkeypatch.setattr(DOMSnapshotCascade, '_semantic', "
            "SimpleNamespace(score=lambda q, t: 0.9))"
        )

    monkeypatch.setattr(
        "stepper.engine.resolvers.strategies.SemanticResolver.__init__", _refuse
    )
