from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.browser.electron_launcher import ElectronLaunchError, launch_electron_cdp


@pytest.mark.asyncio
async def test_launch_electron_cdp_success():
    """Returns browser.contexts[0] when connect_over_cdp succeeds."""
    mock_context = MagicMock()
    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]

    mock_chromium = MagicMock()
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.stop = AsyncMock()

    mock_async_playwright_instance = MagicMock()
    mock_async_playwright_instance.start = AsyncMock(return_value=mock_pw)

    mock_async_playwright = MagicMock(return_value=mock_async_playwright_instance)

    with patch("engine.browser.electron_launcher.async_playwright", mock_async_playwright):
        result = await launch_electron_cdp(port=9222)

    assert result is mock_context
    mock_chromium.connect_over_cdp.assert_called_once_with("http://localhost:9222")


@pytest.mark.asyncio
async def test_launch_electron_cdp_timeout_raises_error():
    """Raises ElectronLaunchError with port in message when all retries fail."""
    mock_chromium = MagicMock()
    mock_chromium.connect_over_cdp = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.stop = AsyncMock()

    mock_async_playwright_instance = MagicMock()
    mock_async_playwright_instance.start = AsyncMock(return_value=mock_pw)

    mock_async_playwright = MagicMock(return_value=mock_async_playwright_instance)

    with patch("engine.browser.electron_launcher.async_playwright", mock_async_playwright):
        with patch("engine.browser.electron_launcher.asyncio.sleep", AsyncMock()):
            with pytest.raises(ElectronLaunchError) as exc_info:
                await launch_electron_cdp(port=9222, timeout_ms=500)

    assert "9222" in str(exc_info.value)
    mock_pw.stop.assert_called_once()
