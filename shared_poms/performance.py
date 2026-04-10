from __future__ import annotations

import json
import logging
from pathlib import Path

from shared_poms.interfaces import IBrowserDriver

logger = logging.getLogger(__name__)


async def measure_page_performance(
    driver: IBrowserDriver,
    url: str,
    threshold_ms: int,
    output_path: str | Path,
) -> dict:
    # "load" is required so the Navigation Timing API records loadEventEnd.
    # OpenLibrary can be slow — 60s timeout prevents hanging indefinitely.
    await driver.goto(url, wait_until="load", timeout=60_000)
    metrics = await driver.evaluate(
        """
        () => {
          const nav = performance.getEntriesByType('navigation')[0];
          if (!nav) return {};
          return {
            dom_content_loaded_ms: nav.domContentLoadedEventEnd - nav.startTime,
            load_time_ms: nav.loadEventEnd - nav.startTime,
            first_byte_ms: nav.responseStart - nav.startTime,
            response_end_ms: nav.responseEnd - nav.startTime,
            transfer_size: nav.transferSize,
          };
        }
        """
    )
    # first_paint via PerformancePaintTiming (not in navigation entry)
    first_paint = await driver.evaluate(
        """
        () => {
          const entries = performance.getEntriesByName('first-paint');
          return entries.length ? entries[0].startTime : null;
        }
        """
    )
    if first_paint is not None:
        metrics["first_paint_ms"] = first_paint

    load_ms = metrics.get("load_time_ms", 0)
    if load_ms > threshold_ms:
        logger.warning(
            "Performance threshold exceeded on %s: %.0fms > %dms",
            url, load_ms, threshold_ms,
        )

    output = {"url": url, "threshold_ms": threshold_ms, "metrics": metrics}
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output
