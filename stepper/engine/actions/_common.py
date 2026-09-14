"""
actions/_common.py — helpers shared by more than one action module.

Private to engine.actions: nothing outside the package should need these.
"""

from __future__ import annotations
import asyncio
import os

from stepper.engine.interfaces import StepConfig, StepResult


async def _wait_for(page, selector: str):
    try:
        if "/" in selector and not selector.startswith("//"):
            await page.wait_for_url(f"**{selector}**", timeout=10_000)
        else:
            await page.wait_for_selector(selector, timeout=10_000)
    except Exception:
        await asyncio.sleep(2)


def _resolve_input_value(value: str) -> tuple[str, bool]:
    if not isinstance(value, str):
        return value, False
    if value.startswith("ENV:"):
        key = value.split("ENV:", 1)[1]
        return os.environ.get(key, ""), True
    if value.startswith("${ENV:") and value.endswith("}"):
        key = value[6:-1]
        return os.environ.get(key, ""), True
    return value, False


async def _fetch_attr(locator, attr: str) -> str:
    """Fetch a single DOM attribute from a Playwright locator."""
    if attr == "innerText":
        return (await locator.inner_text()).strip()
    if attr == "innerHTML":
        return await locator.inner_html()
    if attr == "textContent":
        return (await locator.text_content() or "").strip()
    return await locator.get_attribute(attr) or ""


def _checked_input_value(step: StepConfig) -> tuple[str, StepResult | None]:
    """Resolve input_value, returning (value, None) on success or ("", StepResult) on missing env var."""
    value, was_env = _resolve_input_value(step.input_value)
    if was_env and not value:
        return "", StepResult(
            step=step,
            status="failed",
            error=f"Missing environment variable for value '{step.input_value}'",
        )
    return value, None
