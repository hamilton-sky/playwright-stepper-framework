"""
healer/annotator.py — Post-heal screenshot annotator.

After a step is successfully healed, captures a page screenshot and draws a
red bounding box around the element identified by the healed cfg.  Requires
Pillow; silently skips if Pillow is not installed or the element is not visible.
"""

from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _locator_from_cfg(page, cfg: dict):
    """Map a healed cfg dict to a Playwright locator (best effort)."""
    if "placeholder" in cfg:
        return page.get_by_placeholder(cfg["placeholder"]).first
    if "role" in cfg and "name" in cfg:
        return page.get_by_role(cfg["role"], name=cfg["name"]).first
    if "label" in cfg:
        return page.get_by_label(cfg["label"]).first
    if "text" in cfg:
        return page.get_by_text(cfg["text"]).first
    if "id" in cfg:
        return page.locator(f"#{cfg['id']}").first
    if "css" in cfg:
        return page.locator(cfg["css"]).first
    if "xpath" in cfg:
        return page.locator(f"xpath={cfg['xpath']}").first
    return None


class HealAnnotator:
    """
    Captures a screenshot and overlays a red bounding box on the healed element.

    Usage:
        path = await HealAnnotator.capture(page, healed_cfg, step_idx=2,
                                           label="healed", screenshots_dir=Path(...))
    Returns the saved file path as a string, or None on any failure.
    """

    @staticmethod
    async def capture(
        page,
        healed_cfg: dict,
        step_idx: int,
        label: str,
        screenshots_dir: Path,
    ) -> str | None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            logger.debug("[HealAnnotator] Pillow not installed — skipping annotation")
            return None

        try:
            locator = _locator_from_cfg(page, healed_cfg)
            if locator is None:
                return None

            bbox = await locator.bounding_box()
            if not bbox:
                logger.debug("[HealAnnotator] bounding_box() returned None")
                return None

            from io import BytesIO
            screenshot_bytes = await page.screenshot(full_page=False)
            img = Image.open(BytesIO(screenshot_bytes)).convert("RGBA")

            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            pad = 4
            # Semi-transparent red fill + solid red border
            draw.rectangle(
                [x - pad, y - pad, x + w + pad, y + h + pad],
                outline=(220, 38, 38, 255),
                width=3,
                fill=(220, 38, 38, 40),
            )
            # Label badge above the element
            badge = f" {label} "
            bw = len(badge) * 8
            bx, by = max(int(x) - pad, 0), max(int(y) - pad - 20, 0)
            draw.rectangle([bx, by, bx + bw, by + 18], fill=(220, 38, 38, 220))
            draw.text((bx + 2, by + 2), badge, fill=(255, 255, 255, 255))

            combined = Image.alpha_composite(img, overlay).convert("RGB")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            out_path = screenshots_dir / f"step_{step_idx:02d}_healed_annotated.png"
            combined.save(str(out_path))
            logger.info(f"[HealAnnotator] annotated screenshot → {out_path.name}")
            return str(out_path)

        except Exception as exc:
            logger.debug(f"[HealAnnotator] annotation failed: {exc}")
            return None
