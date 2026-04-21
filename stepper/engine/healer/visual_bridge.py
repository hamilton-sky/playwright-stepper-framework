"""
healer/visual_bridge.py — Fast pre-flight check before the AI healing cascade.

Detects elements that exist in the DOM but are hidden or disabled,
short-circuiting the expensive DOMSnapshotCascade + AiHealer call.
"""

from __future__ import annotations

VISIBILITY_WAIT_S = 2.0


class VisualBridge:

    @staticmethod
    def _best_locator(page, step):
        """Return a Playwright locator for the step's element, or None."""
        el = step.element
        if not el:
            return None

        if "role" in el and "name" in el:
            return page.get_by_role(el["role"], name=el["name"])
        if "label" in el:
            return page.get_by_label(el["label"])
        if "placeholder" in el:
            return page.get_by_placeholder(el["placeholder"])
        if "id" in el:
            return page.locator(f"#{el['id']}")
        if "css" in el:
            return page.locator(el["css"])
        return None

    @classmethod
    async def check(cls, page, step) -> str | None:
        """
        Returns:
            None      — element not found in DOM, let cascade proceed
            "hidden"  — element exists but is not visible
            "disabled"— element exists and visible but not enabled
            "ok"      — element is visible and enabled
        """
        try:
            locator = cls._best_locator(page, step)
            if locator is None:
                return None

            if locator.count() == 0:
                return None

            if not await locator.first.is_visible():
                import asyncio
                await asyncio.sleep(VISIBILITY_WAIT_S)
                if not await locator.first.is_visible():
                    return "hidden"

            if not await locator.first.is_enabled():
                return "disabled"

            return "ok"
        except Exception:
            return None
