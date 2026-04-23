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

from engine.interfaces import ReporterStrategy, StepResult
from engine.reporter.test_report_manager import TestReportManager

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

    def start_suite(self, name: str):
        """Initialize test report directory."""
        self._suite_name = name
        self._results.clear()
        self._start_time = datetime.now()
        self._step_num = 0

        # Create test directory
        test_dir = self.manager.create_test_report_dir(
            test_name=self.test_name,
            run_num=self.run_num
        )
        
        logger.info(f"Started test suite: {name} → {test_dir}")
        return test_dir

    def record_step(self, result: StepResult):
        """Record step result. Screenshots are already written directly to the
        run's reports/screenshots/ directory by the action — no copy needed."""
        self._results.append(result)
        self._step_num += 1
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
        from pathlib import Path as _Path
        suite_stem = _Path(self._suite_name).stem if self._suite_name else self._suite_name
        self.manager.save_metadata({
            "test_name": self._test_name,
            "suite_name": suite_stem,
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
            "suite": suite_stem,
            "started_at": self._start_time.isoformat(),
            "total_steps": len(self._results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total_duration_ms": total_duration_ms,
            "success_rate": passed / (passed + failed) if (passed + failed) > 0 else 1.0,
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
                "error": r.error if r.status != "skipped" else "",
                "skip_reason": r.skip_reason if r.status == "skipped" else "",
                "output": r.output or None,
                **({"heal_attempts": r.heal_attempts} if r.heal_attempts > 0 else {}),
            }
            for i, r in enumerate(self._results)
        ]
        self.manager.save_step_results(step_results)
        
        # Collect performance metrics
        active_steps = [r for r in self._results if r.status != "skipped"]
        performance = {
            "total_duration_ms": total_duration_ms,
            "avg_step_duration_ms": total_duration_ms / len(active_steps) if active_steps else 0,
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

        test_dir = self.manager.current_test_dir
        result_msg = f"{passed}/{len(self._results)} passed"
        logger.info(f"Test suite completed: {result_msg} → {test_dir}")

        return f"Report saved to: {test_dir}"

    @property
    def _test_name(self) -> str:
        return self.test_name
