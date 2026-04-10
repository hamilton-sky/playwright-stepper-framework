"""
Enhanced reporters with TestReportReporter for per-test directory organization.

Integrates with TestReportManager to organize outputs by test ID.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from stepper.interfaces import ReporterStrategy, StepResult
from stepper.reporter.test_report_manager import TestReportManager

logger = logging.getLogger(__name__)


class TestReportReporter(ReporterStrategy):
    """
    Organizes test reports in per-test directories using TestReportManager.
    
    Creates structure:
    reports/
    └── test-{ID}/
        ├── metadata.json
        ├── summary.json
        ├── results.json
        ├── performance.json
        ├── screenshots/
        ├── logs/
        └── attachments/
    """

    def __init__(
        self,
        reports_base: str = "reports",
        test_name: str = "unnamed_test",
        run_num: int = 1,
        browser: str = "chromium",
        headless: bool = True,
    ):
        self.manager = TestReportManager(reports_base=reports_base)
        self.test_name = test_name
        self.run_num = run_num
        self._browser = browser
        self._headless = headless
        
        self._results: list[StepResult] = []
        self._suite_name = ""
        self._start_time: datetime | None = None
        self._metadata: dict[str, Any] = {}
        self._step_num = 0
        self._screenshots_dir = Path("artifacts/screenshots")
        self._existing_screenshots: set[Path] = set()

    def start_suite(self, name: str):
        """Initialize test report directory."""
        self._suite_name = name
        self._results.clear()
        self._start_time = datetime.now()
        self._step_num = 0

        # Snapshot existing screenshots so we can detect new ones at finish
        if self._screenshots_dir.exists():
            self._existing_screenshots = set(self._screenshots_dir.glob("*.png"))
        else:
            self._existing_screenshots = set()

        # Create test directory
        test_dir = self.manager.create_test_report_dir(
            test_name=self.test_name,
            run_num=self.run_num
        )
        
        logger.info(f"Started test suite: {name} → {test_dir}")
        return test_dir

    def record_step(self, result: StepResult):
        """Record step result and save screenshot(s)."""
        self._results.append(result)
        self._step_num += 1

        step_desc = result.step.description or result.step.action

        # Multi-shot action (e.g. ol_add_to_shelf): copy each individually
        if result.screenshots:
            for i, shot in enumerate(result.screenshots, start=1):
                if Path(shot).exists():
                    self.manager.copy_screenshot(
                        source_path=Path(shot),
                        step_name=f"{step_desc}_book_{i}",
                        step_num=self._step_num,
                    )
        elif result.screenshot and Path(result.screenshot).exists():
            self.manager.copy_screenshot(
                source_path=Path(result.screenshot),
                step_name=step_desc,
                step_num=self._step_num,
            )

        logger.info(
            f"Recorded step {self._step_num}: "
            f"{result.step.action} → {result.status}"
        )

    def finish_suite(self) -> str:
        """Finalize test report with all outputs."""
        if not self._start_time:
            return "No suite started"
        
        # Calculate durations
        end_time = datetime.now()
        total_duration_ms = int((end_time - self._start_time).total_seconds() * 1000)
        
        # Save metadata
        self.manager.save_metadata({
            "test_name": self._test_name,
            "suite_name": self._suite_name,
            "browser": self._browser,
            "headless": self._headless,
            "total_duration_ms": total_duration_ms,
            "step_count": len(self._results),
        })
        
        # Calculate summary
        passed  = sum(1 for r in self._results if r.status == "passed")
        failed  = sum(1 for r in self._results if r.status == "failed")
        skipped = sum(1 for r in self._results if r.status == "skipped")
        
        summary = {
            "suite": self._suite_name,
            "started_at": self._start_time.isoformat(),
            "total_steps": len(self._results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total_duration_ms": total_duration_ms,
            "success_rate": passed / len(self._results) if self._results else 0.0,
        }
        self.manager.save_summary(summary)
        
        # Save step results
        step_results = [
            {
                "num": i + 1,
                "description": r.step.description or r.step.action,
                "action": r.step.action,
                "status": r.status,
                "confidence": round(r.confidence, 3),
                "duration_ms": r.duration_ms,
                "screenshots": [Path(s).name for s in r.screenshots] if r.screenshots else (
                    [Path(r.screenshot).name] if r.screenshot else []
                ),
                "error": r.error,
            }
            for i, r in enumerate(self._results)
        ]
        self.manager.save_step_results(step_results)
        
        # Collect performance metrics
        performance = {
            "total_duration_ms": total_duration_ms,
            "avg_step_duration_ms": total_duration_ms / len(self._results) if self._results else 0,
            "steps": [
                {
                    "num": i + 1,
                    "name": r.step.description or r.step.action,
                    "duration_ms": r.duration_ms,
                }
                for i, r in enumerate(self._results)
            ],
        }
        self.manager.save_performance_metrics(performance)
        
        # Generate cross-test summary
        self.manager.generate_cross_test_summary()

        # Copy flat report.json into attachments/ for per-run archiving
        import shutil
        flat_report = Path("report.json")
        if flat_report.exists() and self.manager.current_test_dir:
            shutil.copy(flat_report, self.manager.current_test_dir / "attachments" / "report.json")

        test_dir = self.manager.current_test_dir
        result_msg = f"{passed}/{len(self._results)} passed"
        logger.info(f"Test suite completed: {result_msg} → {test_dir}")

        return f"Report saved to: {test_dir}"

    @property
    def _test_name(self) -> str:
        return self.test_name
