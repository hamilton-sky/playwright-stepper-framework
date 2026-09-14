"""
actions/measurement.py — judge the rendered result against a threshold.

measure_performance compares navigation timings against a budget;
visual_compare compares a screenshot against a stored baseline. Both write an
artifact under stepper/artifacts/ and both fail the step on a regression, which
is what separates them from the plain `screenshot` action in basic.py.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
)

logger = logging.getLogger(__name__)

# Absolute path to stepper/ — used to resolve relative output paths in workflow
# JSON files so artifacts always land inside stepper/ regardless of cwd.
_stepper_root = Path(__file__).resolve().parent.parent.parent


class MeasurePerformanceAction(ActionStrategy):
    """
    Bonus: navigate to URL and measure web performance metrics.
    Writes performance_report.json.
    Exam bonus requirement.
    """
    action_name = "measure_performance"
    read_only   = True

    def __init__(self):
        # Path only — the directory is created when a run actually writes to it.
        # build_default_registry() constructs every action, so a mkdir here made
        # read-only commands like `list` and `actions` create directories.
        self._default_output = _stepper_root / "artifacts" / "performance.json"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        url       = step.url or step.input_value
        threshold = step.extra.get("threshold_ms", 3000)

        await page.goto(url, wait_until="networkidle", timeout=30_000)

        metrics = await page.evaluate("""() => {
            const t = performance.timing;
            const p = performance.getEntriesByType('paint');
            return {
                load_time_ms:            t.loadEventEnd - t.navigationStart,
                dom_content_loaded_ms:   t.domContentLoadedEventEnd - t.navigationStart,
                first_paint_ms:          p.find(e => e.name === 'first-paint')?.startTime || null
            };
        }""")

        report = {**metrics, "url": url, "threshold_ms": threshold}

        if metrics["load_time_ms"] > threshold:
            logger.warning(f"Performance threshold exceeded: {metrics['load_time_ms']}ms > {threshold}ms")

        raw_path = Path(step.extra.get("output_path", "artifacts/performance.json"))
        output_path = raw_path if raw_path.is_absolute() else _stepper_root / raw_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"performance: {metrics} → {output_path}")
        return StepResult(step=step, status="passed")


class VisualCompareAction(ActionStrategy):
    """
    Take a screenshot and compare it against a stored baseline.

    First run (no baseline exists): saves the screenshot as the baseline and
    passes — so the first run always bootstraps the baseline automatically.

    Subsequent runs: pixel-diffs the current screenshot against the baseline.
    If the diff ratio exceeds `threshold` (default 0.01 = 1%), the step fails
    and a diff image is written next to the baseline for review.

    Step config (extra keys):
        snapshot_name  str   Required. Unique name for this comparison point.
                             e.g. "search-results-dune" or "shelf-after-add"
        threshold      float Optional. Max allowed diff ratio (0.0–1.0). Default 0.01.
        full_page      bool  Optional. Full-page screenshot. Default False.
        update         bool  Optional. If true, overwrite baseline with current shot.
                             Use this when an intentional UI change is approved.

    Baselines are stored in:  stepper/artifacts/baselines/<snapshot_name>.png
    Diff images are stored in: stepper/artifacts/baselines/<snapshot_name>.diff.png
    (engine-level; site-specific artifacts live under stepper/sites/<site>/artifacts/)

    JSON example:
        {
            "action": "visual_compare",
            "description": "Shelf state after adding Dune books",
            "extra": {
                "snapshot_name": "shelf-after-dune-add",
                "threshold": 0.02
            }
        }

    To update a baseline after an approved UI change:
        {
            "action": "visual_compare",
            "extra": { "snapshot_name": "shelf-after-dune-add", "update": true }
        }
    """
    action_name = "visual_compare"
    read_only   = True

    def __init__(self):
        # Path only; created on first write. See MeasurePerformanceAction.
        self._baselines_dir = _stepper_root / "artifacts" / "baselines"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        from PIL import Image, ImageChops, ImageEnhance
        import io
        import numpy as np

        snapshot_name = step.extra.get("snapshot_name")
        if not snapshot_name:
            return StepResult(
                step=step, status="failed",
                error="visual_compare requires extra.snapshot_name"
            )

        threshold  = float(step.extra.get("threshold", 0.01))
        full_page  = bool(step.extra.get("full_page", False))
        do_update  = bool(step.extra.get("update", False))

        baseline_path = self._baselines_dir / f"{snapshot_name}.png"
        diff_path     = self._baselines_dir / f"{snapshot_name}.diff.png"

        # Capture current state
        raw_bytes = await page.screenshot(full_page=full_page)
        current   = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

        # Update mode: overwrite baseline and pass
        if do_update:
            self._baselines_dir.mkdir(parents=True, exist_ok=True)
            current.save(str(baseline_path))
            logger.info(f"visual_compare: baseline updated → {baseline_path}")
            return StepResult(step=step, status="passed",
                              output={"snapshot": snapshot_name, "mode": "updated"})

        # First run: no baseline yet — save and pass
        if not baseline_path.exists():
            self._baselines_dir.mkdir(parents=True, exist_ok=True)
            current.save(str(baseline_path))
            logger.info(f"visual_compare: baseline created → {baseline_path}")
            return StepResult(step=step, status="passed",
                              output={"snapshot": snapshot_name, "mode": "baseline_created"})

        # Compare against baseline
        baseline = Image.open(str(baseline_path)).convert("RGB")

        # Resize current to match baseline dimensions if they differ
        # (can happen after viewport changes)
        if current.size != baseline.size:
            current = current.resize(baseline.size, Image.LANCZOS)

        diff_image = ImageChops.difference(baseline, current)

        # Count pixels where any channel differs by more than 8/255 (noise floor).
        # Vectorised rather than a Python loop over getdata(): the same count,
        # ~7x faster on a full-page screenshot (0.34s -> 0.05s at 1280x800), and
        # getdata() is deprecated for removal in Pillow 14.
        diff_array = np.asarray(diff_image)
        height, width = diff_array.shape[0], diff_array.shape[1]
        total      = height * width
        changed    = int((diff_array.max(axis=2) > 8).sum())
        diff_ratio = changed / total

        if diff_ratio > threshold:
            # Amplify diff image so small differences are visible
            amplified = ImageEnhance.Brightness(diff_image).enhance(10)
            amplified.save(str(diff_path))
            msg = (
                f"Visual diff {diff_ratio:.2%} exceeds threshold {threshold:.2%} "
                f"for '{snapshot_name}'. Diff image → {diff_path}"
            )
            logger.warning(msg)
            return StepResult(
                step=step, status="failed", error=msg,
                screenshot=str(diff_path),
                output={"snapshot": snapshot_name, "diff_ratio": round(diff_ratio, 6),
                        "threshold": threshold, "diff_image": str(diff_path)},
            )

        logger.info(f"visual_compare: '{snapshot_name}' passed (diff={diff_ratio:.4%})")
        return StepResult(
            step=step, status="passed",
            output={"snapshot": snapshot_name, "diff_ratio": round(diff_ratio, 6),
                    "threshold": threshold},
        )
