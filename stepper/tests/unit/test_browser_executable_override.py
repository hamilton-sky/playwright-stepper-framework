"""
BROWSER_EXECUTABLE_PATH — running against a browser Playwright did not fetch.

Playwright refuses to launch unless the exact chromium revision its version
expects is on disk. requirements.txt pins the version whose revision matches
the container this repo runs in, which is the real fix; this is the escape
hatch for when that stops being true — a prebuilt image often ships one
revision and no way to download another, so a version bump there turns every
run into "please run playwright install", which is the one thing such an image
cannot do.

No browser is launched here: these check the kwargs handed to launch().
"""
from __future__ import annotations

import pytest

from poms.shared.driver import browser_launch_kwargs

_VAR = "BROWSER_EXECUTABLE_PATH"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(_VAR, raising=False)


def test_no_override_means_no_extra_kwargs():
    """The default must stay exactly what launch() saw before this existed."""
    assert browser_launch_kwargs() == {}


def test_a_real_path_is_passed_through(monkeypatch, tmp_path):
    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setenv(_VAR, str(binary))

    assert browser_launch_kwargs() == {"executable_path": str(binary)}


def test_a_path_that_does_not_exist_is_ignored(monkeypatch, caplog):
    """
    A stale value in someone's .env degrades to normal behaviour rather than
    breaking every run — but it says so, because silently ignoring the setting
    someone deliberately made is its own kind of confusing.
    """
    monkeypatch.setenv(_VAR, "/nope/not-here")

    with caplog.at_level("WARNING"):
        assert browser_launch_kwargs() == {}

    assert "/nope/not-here" in caplog.text


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_value_is_not_an_override(blank, monkeypatch):
    """An env var set to empty is the usual shape of a half-filled .env."""
    monkeypatch.setenv(_VAR, blank)

    assert browser_launch_kwargs() == {}


def test_surrounding_whitespace_is_trimmed(monkeypatch, tmp_path):
    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setenv(_VAR, f"  {binary}  ")

    assert browser_launch_kwargs() == {"executable_path": str(binary)}


async def test_launch_browser_forwards_the_override(monkeypatch, tmp_path):
    """The engine's launcher honours it, not just the parallel one."""
    from unittest.mock import AsyncMock, MagicMock

    from stepper.bootstrap.infra import launch_browser

    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setenv(_VAR, str(binary))

    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value="the-browser")

    assert await launch_browser(pw, "chromium", True, 0) == "the-browser"
    assert pw.chromium.launch.await_args.kwargs["executable_path"] == str(binary)


async def test_launch_browser_passes_nothing_extra_by_default():
    from unittest.mock import AsyncMock, MagicMock

    from stepper.bootstrap.infra import launch_browser

    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value="the-browser")

    await launch_browser(pw, "chromium", True, 0)

    assert "executable_path" not in pw.chromium.launch.await_args.kwargs


async def test_the_parallel_launcher_honours_it_too(monkeypatch, tmp_path):
    """
    ParallelAction's isolated_browser mode spawns its own browsers through
    PlaywrightBrowserLauncher, which would otherwise ignore the override and
    fail where the main launch had just succeeded.
    """
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from poms.shared.driver import PlaywrightBrowserLauncher

    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setenv(_VAR, str(binary))

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=MagicMock(
        new_page=AsyncMock(return_value="the-page")))
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    starter = MagicMock(start=AsyncMock(return_value=pw))
    monkeypatch.setitem(
        sys.modules, "playwright.async_api",
        SimpleNamespace(async_playwright=lambda: starter),
    )

    _handle, page = await PlaywrightBrowserLauncher(headless=True).create_page()

    assert page == "the-page"
    assert pw.chromium.launch.await_args.kwargs["executable_path"] == str(binary)
