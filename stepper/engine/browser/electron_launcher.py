"""
engine/browser/electron_launcher.py — Generic Electron CDP launcher.

Connects Playwright to a running Electron process via Chrome DevTools Protocol.
Electron must be started with --remote-debugging-port=<port>.

No Pathly-specific imports — this module is generic and reusable.
"""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class ElectronLaunchError(Exception):
    """Raised when Playwright cannot connect to Electron via CDP within the timeout."""


async def launch_electron_cdp(port: int, timeout_ms: int = 30000):
    """
    Connect to a running Electron app via Chrome DevTools Protocol.

    Retries every 500ms until timeout_ms is exhausted.
    Returns the first BrowserContext exposed by the connected browser.

    Electron must be launched with --remote-debugging-port=<port>.
    """
    deadline_ms = timeout_ms
    interval_ms = 500
    pw = await async_playwright().start()

    while deadline_ms > 0:
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
            logger.debug("launch_electron_cdp: connected on port %d", port)
            return browser.contexts[0]
        except Exception:
            await asyncio.sleep(interval_ms / 1000)
            deadline_ms -= interval_ms

    await pw.stop()
    raise ElectronLaunchError(
        f"Could not connect to Electron on CDP port {port}. "
        f"Is Electron running with --remote-debugging-port={port}?"
    )
