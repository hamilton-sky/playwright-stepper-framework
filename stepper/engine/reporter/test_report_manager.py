"""
test_report_manager.py — Manages per-test report directories and outputs.

Pattern: Factory + Builder
  Creates test-specific report directories.
  Organizes screenshots, JSON, Allure, and logs by test ID.

OCP: Add new report types without modifying this module.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TestReportManager:
    """
    Manages directory structure for reports organized by Test ID.
    
    Each test execution gets:
    - test-{ID}/ folder with screenshots/, logs/, attachments/
    - metadata.json with test environment info
    - summary.json with pass/fail counts
    - results.json with step details
    - performance.json with timing data
    """

    def __init__(self, reports_base: str = "reports"):
        self.reports_base = Path(reports_base)
        self.reports_base.mkdir(parents=True, exist_ok=True)
        
        self.current_test_id: str | None = None
        self.current_test_dir: Path | None = None
        
    def create_test_report_dir(self, test_name: str, run_num: int = 1) -> Path:
        """
        Create a new test report directory with unique ID.
        
        Args:
            test_name: Name of the test (e.g., 'exam_001', 'search_and_add')
            run_num: Run number for this test today
            
        Returns:
            Path to the created test directory
            
        Example:
            manager.create_test_report_dir('exam_001', 1)
            → reports/test-20260331_134509_exam_001_001/
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")

        # Sanitize test name
        safe_name = test_name.lower().replace(" ", "_").replace("/", "_")

        # Create unique ID: 2026-04-05_23-59-27_ol_search_and_add_001
        self.current_test_id = f"{date_str}_{time_str}_{safe_name}_{run_num:03d}"
        self.current_test_dir = self.reports_base / self.current_test_id
        
        # Create sub-directories
        subdirs = [
            self.current_test_dir,
            self.current_test_dir / "screenshots",
            self.current_test_dir / "videos",
            self.current_test_dir / "logs",
            self.current_test_dir / "attachments",
        ]
        
        for subdir in subdirs:
            subdir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created test report directory: {self.current_test_dir}")
        
        return self.current_test_dir
    
    def get_screenshots_dir(self) -> Path:
        """Get screenshots directory for current test."""
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        return self.current_test_dir / "screenshots"
    
    def get_logs_dir(self) -> Path:
        """Get logs directory for current test."""
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        return self.current_test_dir / "logs"
    
    def save_metadata(self, metadata: dict[str, Any]) -> None:
        """
        Save test metadata (browser, environment, timestamps).
        
        Args:
            metadata: Dict with test environment info
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        metadata_file = self.current_test_dir / "metadata.json"
        metadata["test_id"] = self.current_test_id
        metadata["created_at"] = datetime.now().isoformat()
        
        metadata_file.write_text(
            json.dumps(metadata, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Saved metadata: {metadata_file}")
    
    def save_summary(self, summary: dict[str, Any]) -> None:
        """
        Save test summary (pass/fail counts, duration).
        
        Args:
            summary: Dict with test results summary
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        summary_file = self.current_test_dir / "summary.json"
        summary["test_id"] = self.current_test_id
        summary["finished_at"] = datetime.now().isoformat()
        
        summary_file.write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Saved summary: {summary_file}")
    
    def save_step_results(self, results: list[dict[str, Any]]) -> None:
        """
        Save detailed step-by-step results.
        
        Args:
            results: List of step result dicts
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        results_file = self.current_test_dir / "results.json"
        output = {
            "test_id": self.current_test_id,
            "steps": results,
        }
        
        results_file.write_text(
            json.dumps(output, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Saved results: {results_file}")
    
    def save_performance_metrics(self, metrics: dict[str, Any]) -> None:
        """
        Save performance metrics (step timings, page load times, etc.).
        
        Args:
            metrics: Dict with performance data
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        perf_file = self.current_test_dir / "step_timings.json"
        metrics["test_id"] = self.current_test_id
        metrics["recorded_at"] = datetime.now().isoformat()
        
        perf_file.write_text(
            json.dumps(metrics, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Saved step timings: {perf_file}")
    
    def copy_screenshot(self, source_path: Path, step_name: str, step_num: int) -> Path:
        """
        Copy screenshot to test report directory with standardized naming.
        
        Args:
            source_path: Path to source screenshot
            step_name: Name of the step (for filename)
            step_num: Sequential step number
            
        Returns:
            Path to destination screenshot
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        # Sanitize step name
        safe_name = step_name.lower().replace(" ", "_").replace("/", "_")
        
        # Create filename: 01_step_name.png
        filename = f"{step_num:02d}_{safe_name}.png"
        dest_path = self.get_screenshots_dir() / filename
        
        if source_path.exists():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(source_path.read_bytes())
            logger.info(f"Copied screenshot: {source_path} → {dest_path}")
        
        return dest_path
    
    def save_console_log(self, log_content: str) -> Path:
        """
        Save console/browser output to logs directory.
        
        Args:
            log_content: Console output text
            
        Returns:
            Path to log file
        """
        if not self.current_test_dir:
            raise RuntimeError("No test report directory created yet")
        
        log_file = self.get_logs_dir() / "console.log"
        log_file.write_text(log_content, encoding="utf-8")
        logger.info(f"Saved console log: {log_file}")
        
        return log_file
    
    def generate_cross_test_summary(self) -> Path:
        """
        Generate a summary report across all tests in reports/ folder.
        
        Returns:
            Path to summary JSON file
        """
        summary_file = self.reports_base / "summary" / "all_tests_summary.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Scan all test run directories (format: YYYY-MM-DD_HH-MM-SS_name_NNN)
        test_dirs = sorted(self.reports_base.glob("????-??-??_*"))
        
        all_tests = []
        total_passed = 0
        total_failed = 0
        
        for test_dir in test_dirs:
            summary_path = test_dir / "summary.json"
            if summary_path.exists():
                data = json.loads(summary_path.read_text(encoding="utf-8"))
                all_tests.append(data)
                total_passed += data.get("passed", 0)
                total_failed += data.get("failed", 0)
        
        output = {
            "generated_at": datetime.now().isoformat(),
            "total_tests": len(all_tests),
            "total_passed": total_passed,
            "total_failed": total_failed,
            "success_rate": (
                total_passed / (total_passed + total_failed)
                if (total_passed + total_failed) > 0 else 1.0
            ),
            "tests": all_tests,
        }
        
        summary_file.write_text(
            json.dumps(output, indent=2, default=str),
            encoding="utf-8"
        )
        logger.info(f"Generated cross-test summary: {summary_file}")
        
        return summary_file
