"""
Unit tests for the Pathly glue action modules.

Tests use patch to mock POM classes so no Playwright/Electron dependency is needed.
"""
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.interfaces import ExecutionContext
from sites.pathly.pages.home_screen_action import PathlyHomeScreen


def _make_step(action="noop", extra=None):
    return SimpleNamespace(
        action=action,
        description="test step",
        element={},
        extra=extra or {},
    )


def _make_context():
    return ExecutionContext()


def _make_page():
    page = MagicMock()
    return page


@pytest.mark.asyncio
async def test_open_project_calls_pom_method():
    """PathlyOpenProjectAction should call open_project(project_name) on the POM."""
    mock_home = MagicMock()
    mock_home.open_project = AsyncMock()

    step = _make_step(extra={"project_name": "MyProject"})
    page = _make_page()
    context = _make_context()

    action = PathlyHomeScreen.PathlyOpenProjectAction()

    with patch.object(action, "_driver", return_value=MagicMock()):
        with patch.object(action, "_build_pom", return_value=mock_home):
            # patch the lazy import so no real pom is loaded
            with patch("sites.pathly.pages.home_screen_action.PathlyHomeScreen.PathlyOpenProjectAction._execute",
                       wraps=action._execute):
                result = await action._execute(
                    page=page,
                    step=step,
                    resolver=None,
                    context=context,
                    behaviour=None,
                )

    mock_home.open_project.assert_awaited_once_with("MyProject")
    assert result.status == "passed"


@pytest.mark.asyncio
async def test_assert_projects_fails_when_project_missing():
    """PathlyAssertProjectsAction should fail when expected project is absent."""
    mock_home = MagicMock()
    mock_home.get_project_names = AsyncMock(return_value=["A"])

    step = _make_step(extra={"expected_names": ["A", "B"]})
    page = _make_page()
    context = _make_context()

    action = PathlyHomeScreen.PathlyAssertProjectsAction()

    with patch.object(action, "_driver", return_value=MagicMock()):
        with patch.object(action, "_build_pom", return_value=mock_home):
            result = await action._execute(
                page=page,
                step=step,
                resolver=None,
                context=context,
                behaviour=None,
            )

    assert result.status == "failed"
    assert "B" in result.error
