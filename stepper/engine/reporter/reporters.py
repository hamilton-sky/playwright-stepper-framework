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

from stepper.engine.interfaces import ReporterStrategy, StepResult

logger = logging.getLogger(__name__)


def _safe_print(text: str) -> None:
    """Print safely on Windows consoles that don't support Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def _status_details(result: StepResult) -> dict:
    """
    The one-line explanation Allure shows beside a step.

    A skip carries its reason and never an error; a heal that succeeded has no
    error left to show, so say that it healed rather than leaving it looking
    like an ordinary pass.
    """
    if result.status == "skipped" and result.skip_reason:
        return {"message": result.skip_reason}
    if result.status == "healed":
        healed = result.healed_element or {}
        if healed.get("healed"):
            return {"message": f"healed: element resolved to {healed['healed']}"}
        return {"message": "healed"}
    if result.error:
        return {"message": result.error}
    return {}


class ConsoleReporter(ReporterStrategy):
    """Prints a simple pass/fail summary to stdout."""

    def __init__(self):
        self._results: list[StepResult] = []
        self._suite_name = ""

    def start_suite(self, name: str):
        self._suite_name = name
        self._results.clear()
        _safe_print(f"\n{'='*55}")
        _safe_print(f"  {name}")
        _safe_print(f"{'='*55}")

    def record_step(self, result: StepResult):
        self._results.append(result)
        icon = {"passed": "OK", "failed": "FAIL", "skipped": "SKIP", "warned": "WARN",
                "healed": "HEAL"}.get(result.status, "...")
        desc = result.step.description or result.step.action
        _safe_print(f"  {icon}  {desc}")
        if result.error:
            safe_error = result.error.encode("ascii", errors="replace").decode("ascii")
            _safe_print(f"       -> {safe_error}")

    def finish_suite(self) -> str:
        passed  = sum(1 for r in self._results if r.status == "passed")
        failed  = sum(1 for r in self._results if r.status == "failed")
        total   = len(self._results)
        summary = f"{passed}/{total} passed"
        _safe_print(f"\n  Result: {summary}  ({failed} failed)\n")
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
        # A healed step failed, was repaired, and then succeeded — so it passed.
        # Allure has no richer status for it, and "broken" would paint a whole
        # suite as broken for doing exactly what the healer exists to do. The
        # fact that it healed is not lost: _status_details() says so, and
        # results.json carries the before/after cfg in healed_element.
        #
        # Without this entry "healed" fell through to "unknown" — the one status
        # that tells a reader nothing — on every run made with --heal.
        "healed":  "passed",
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
            step_entry: dict = {
                "name":          r.step.description or r.step.action,
                "status":        self.STATUS_MAP.get(r.status, "unknown"),
                "start":         t,
                "stop":          t + step_duration,
                "stage":         "finished",
                "statusDetails": _status_details(r),
            }

            # A multi-shot action (for_each_item) produces one screenshot per
            # iteration; attaching only the first would drop the evidence for
            # every iteration after it. `screenshot` is the single-shot case.
            if r.screenshots:
                step_entry["attachments"] = [
                    {
                        "name":   f"screenshot_{i + 1}",
                        "source": Path(path).name,
                        "type":   "image/png",
                    }
                    for i, path in enumerate(r.screenshots)
                ]
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
