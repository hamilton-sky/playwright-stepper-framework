"""
utils/screenshot.py — ScreenshotManager

Single responsibility: own everything about how screenshots are captured
and recorded — naming convention, directory, and Allure attachment.

The orchestrator calls:
    await self._screenshots.capture("book_1")
and knows nothing about file paths, mkdir, or Allure.
"""
from __future__ import annotations

from pathlib import Path

from shared_poms.interfaces import IBrowserDriver


class ScreenshotManager:
    """
    Owns screenshot naming, directory management, and Allure attachment.

    Inject via constructor — never instantiate inside a method body.
    """

    def __init__(self, driver: IBrowserDriver, screenshots_dir: Path) -> None:
        self._driver = driver
        self._dir = screenshots_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, name: str) -> Path:
        """
        Save <name>.png to the configured directory and attach to Allure
        if a test session is active. Returns the saved path.
        """
        path = self._dir / f"{name}.png"
        await self._driver.screenshot(path=str(path))
        self._attach_allure(path, name)
        return path

    @staticmethod
    def _attach_allure(path: Path, name: str) -> None:
        """Attach to Allure when running inside a pytest-allure session; no-op otherwise."""
        try:
            import allure
            from allure_commons.types import AttachmentType
            allure.attach.file(str(path), name=name, attachment_type=AttachmentType.PNG)
        except Exception:
            pass
