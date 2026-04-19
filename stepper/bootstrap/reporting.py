from __future__ import annotations
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def build_reporters(run_label: str, cfg_browser: str, headless: bool, stepper_root: Path):
    from engine.reporter.reporters import CompositeReporter, ConsoleReporter, JsonReporter, AllureReporter
    from engine.reporter.test_report_reporter import TestReportReporter
    test_reporter = TestReportReporter(
        reports_base=str(stepper_root / "reports"),
        test_name=run_label,
        browser=cfg_browser,
        headless=not headless,
    )
    reporters = [
        ConsoleReporter(),
        JsonReporter(str(stepper_root / "report.json")),
        test_reporter,
        AllureReporter(str(stepper_root / "reports" / "allure-results")),
    ]
    return CompositeReporter(reporters), test_reporter


def serve_allure(stepper_root: Path) -> None:
    allure_dir = str(stepper_root / "reports" / "allure-results")
    logger.info(f"Launching: allure serve {allure_dir}")
    subprocess.run(["allure", "serve", allure_dir])
