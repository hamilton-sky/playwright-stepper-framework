"""
reporter/reporters.py — Concrete ReporterStrategy implementations.

Pattern: Strategy
  Swap between ConsoleReporter, JsonReporter, AllureReporter
  without changing any other code.

OCP: Add AllureReporter without touching existing reporters.
SRP: Each reporter only knows how to report, not what to execute.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path

from engine.interfaces import ReporterStrategy, StepResult

logger = logging.getLogger(__name__)


class ConsoleReporter(ReporterStrategy):
    """Prints a simple pass/fail summary to stdout."""

    def __init__(self):
        self._results: list[StepResult] = []
        self._suite_name = ""

    def start_suite(self, name: str):
        self._suite_name = name
        self._results.clear()
        print(f"\n{'='*55}")
        print(f"  {name}")
        print(f"{'='*55}")

    def record_step(self, result: StepResult):
        self._results.append(result)
        icon = {"passed": "OK", "failed": "FAIL", "skipped": "SKIP", "warned": "WARN"}.get(
            result.status, "..."
        )
        desc = result.step.description or result.step.action
        print(f"  {icon}  {desc}")
        if result.error:
            print(f"       -> {result.error}")

    def finish_suite(self) -> str:
        passed  = sum(1 for r in self._results if r.status == "passed")
        failed  = sum(1 for r in self._results if r.status == "failed")
        total   = len(self._results)
        summary = f"{passed}/{total} passed"
        print(f"\n  Result: {summary}  ({failed} failed)\n")
        return summary


class JsonReporter(ReporterStrategy):
    """
    Writes a structured JSON report to disk.
    Exam requirement: performance_report.json + general results.
    """

    def __init__(self, output_path: str = "report.json"):
        self._path    = Path(output_path)
        self._results: list[StepResult] = []
        self._suite   = ""
        self._start   = ""

    def start_suite(self, name: str):
        self._suite   = name
        self._results = []
        self._start   = datetime.now().isoformat()

    def record_step(self, result: StepResult):
        self._results.append(result)

    def finish_suite(self) -> str:
        report = {
            "suite":    self._suite,
            "started":  self._start,
            "finished": datetime.now().isoformat(),
            "passed":   sum(1 for r in self._results if r.status == "passed"),
            "failed":   sum(1 for r in self._results if r.status == "failed"),
            "steps": [
                {
                    "description": r.step.description,
                    "action":      r.step.action,
                    "status":      r.status,
                    "confidence":  round(r.confidence, 3),
                    "screenshot":  r.screenshot,
                    "error":       r.error if r.status != "skipped" else "",
                    "skip_reason": r.skip_reason if r.status == "skipped" else "",
                    "output":      r.output or None,
                }
                for r in self._results
            ]
        }
        self._path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info(f"Report written: {self._path}")
        return str(self._path)


class AllureReporter(ReporterStrategy):
    """
    Writes Allure-compatible JSON results to allure-results/.

    OCP: added without touching ConsoleReporter or JsonReporter.
    SRP: only knows how to write Allure JSON, nothing else.

    Usage:
        reporter = CompositeReporter([ConsoleReporter(), AllureReporter()])

    Then generate the HTML report:
        allure serve allure-results/
    """

    STATUS_MAP = {
        "passed":  "passed",
        "failed":  "failed",
        "skipped": "skipped",
        "warned":  "broken",   # Allure uses "broken" for unexpected warnings
    }

    def __init__(self, output_dir: str = "allure-results"):
        self._dir = Path(output_dir)
        self._dir.mkdir(exist_ok=True)
        self._suite  = ""
        self._start_ms = 0
        self._results: list[StepResult] = []

    def start_suite(self, name: str):
        from pathlib import Path as _Path
        self._suite    = _Path(name).stem if name else name
        self._start_ms = int(datetime.now().timestamp() * 1000)
        self._results  = []

    def record_step(self, result: StepResult):
        self._results.append(result)

    def finish_suite(self) -> str:
        import uuid

        stop_ms = int(datetime.now().timestamp() * 1000)
        step_duration = max(1, (stop_ms - self._start_ms) // max(len(self._results), 1))

        steps_allure = []
        t = self._start_ms
        for r in self._results:
            # ... inside for r in self._results: ...
        
            step_entry: dict = {
            "name":   r.step.description or r.step.action,
            "status": self.STATUS_MAP.get(r.status, "unknown"),
            "start":  t,
            "stop":   t + step_duration,
            "stage":  "finished",
            "statusDetails": ({"message": r.skip_reason} if r.status == "skipped" and r.skip_reason
                              else {"message": r.error} if r.error else {}),
            }

        # Check for the list of screenshots instead of just the single string
            if r.screenshots:
                step_entry["attachments"] = [
                {
                    "name": f"screenshot_{i+1}",
                    "source": Path(path).name,
                    "type": "image/png",
                }
                for i, path in enumerate(r.screenshots)
            ]
        # Fallback for single screenshot if screenshots list is empty
            elif r.screenshot:
                step_entry["attachments"] = [{
                "name":   "screenshot",
                "source": Path(r.screenshot).name,
                "type":   "image/png",
                }]

            steps_allure.append(step_entry)
            t += step_duration

        overall = "passed"
        if any(r.status == "failed" for r in self._results):
            overall = "failed"
        elif any(r.status == "warned" for r in self._results):
            overall = "broken"

        container = {
            "uuid":    str(uuid.uuid4()),
            "name":    self._suite,
            "status":  overall,
            "start":   self._start_ms,
            "stop":    stop_ms,
            "stage":   "finished",
            "steps":   steps_allure,
            "labels":  [
                {"name": "suite",    "value": self._suite},
                {"name": "framework","value": "stepper"},
                {"name": "language", "value": "python"},
            ],
        }

        out_file = self._dir / f"{container['uuid']}-result.json"
        out_file.write_text(json.dumps(container, indent=2), encoding="utf-8")
        logger.info(f"Allure result written: {out_file}")
        return str(out_file)


class CompositeReporter(ReporterStrategy):
    """
    Decorator / Composite: broadcasts to multiple reporters at once.
    Usage: CompositeReporter([ConsoleReporter(), JsonReporter()])
    """

    def __init__(self, reporters: list[ReporterStrategy]):
        self._reporters = reporters

    def start_suite(self, name: str):
        for r in self._reporters:
            r.start_suite(name)

    def record_step(self, result: StepResult):
        for r in self._reporters:
            r.record_step(result)

    def finish_suite(self) -> str:
        return "\n".join(r.finish_suite() for r in self._reporters)
