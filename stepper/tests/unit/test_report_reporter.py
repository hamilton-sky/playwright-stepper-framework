"""
TestReportReporter — the observer that turns a run into the reports/ tree.

It sits between StepRunner and TestReportManager: the manager knows how to write
files, this decides what goes in them. Four artifacts per run, and the numbers
in them are what anyone later reads to decide whether a run was healthy.

The arithmetic is where the risk is, and specifically in what each denominator
excludes. A skipped step is not a failure and must not drag the success rate
down; it is also not a step that took time, so it must not drag the average step
duration down either. Both are easy to get wrong in a way that still produces a
plausible-looking number.
"""
from __future__ import annotations

import json

import pytest

from stepper.engine.interfaces import StepConfig, StepResult

# Aliased: pytest tries to collect anything named Test* that it finds in a test
# module, and this class has an __init__.
from stepper.engine.reporter.test_report_reporter import (
    TestReportReporter as ReportReporter,
)


@pytest.fixture
def reporter(tmp_path) -> ReportReporter:
    return ReportReporter(
        reports_base=str(tmp_path / "reports"),
        test_name="sd_smoke",
        run_num=1,
        browser="firefox",
        headless=False,
    )


def _result(status="passed", description="do the thing", **kw) -> StepResult:
    return StepResult(
        step=StepConfig(action="click", description=description),
        status=status,
        **kw,
    )


def _artifact(reporter: ReportReporter, name: str) -> dict:
    assert reporter.manager.current_test_dir is not None
    return json.loads((reporter.manager.current_test_dir / name).read_text())


def _run(reporter: ReportReporter, *results: StepResult, suite="sd_smoke_test.json") -> None:
    reporter.start_suite(suite)
    for r in results:
        reporter.record_step(r)
    reporter.finish_suite()


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def test_finishing_without_starting_says_so_rather_than_writing_nothing(reporter):
    """
    A run that dies during setup reaches finish_suite with no suite started.
    Writing a zero-step report would put a phantom run in the cross-test summary.
    """
    assert reporter.finish_suite() == "No suite started"
    assert reporter.manager.current_test_dir is None


def test_starting_a_suite_creates_the_run_directory(reporter):
    reporter.start_suite("sd_smoke_test.json")

    assert reporter.manager.current_test_dir is not None
    assert reporter.manager.current_test_dir.is_dir()


def test_all_four_artifacts_are_written(reporter):
    _run(reporter, _result())

    for name in ("metadata.json", "summary.json", "results.json", "step_timings.json"):
        assert (reporter.manager.current_test_dir / name).exists(), f"{name} missing"


def test_a_second_suite_does_not_inherit_the_first_one_s_steps(reporter):
    """The data-driven runner reuses one reporter across rows."""
    _run(reporter, _result("failed"), _result("failed"))
    _run(reporter, _result("passed"))

    assert _artifact(reporter, "summary.json")["total_steps"] == 1


# ── Metadata ──────────────────────────────────────────────────────────────────

def test_metadata_records_how_the_run_was_configured(reporter):
    _run(reporter, _result(), _result())

    metadata = _artifact(reporter, "metadata.json")
    assert metadata["test_name"] == "sd_smoke"
    assert metadata["browser"] == "firefox"
    assert metadata["headless"] is False
    assert metadata["step_count"] == 2


def test_the_suite_name_is_recorded_without_its_path_or_extension(reporter):
    """It is a workflow file path; the stem is what a human recognises."""
    _run(reporter, _result(), suite="stepper/sites/saucedemo/workflows/sd_happy_path.json")

    assert _artifact(reporter, "metadata.json")["suite_name"] == "sd_happy_path"


# ── Summary arithmetic ────────────────────────────────────────────────────────

def test_the_summary_counts_each_status(reporter):
    _run(reporter, _result("passed"), _result("failed"), _result("skipped"), _result("passed"))

    summary = _artifact(reporter, "summary.json")
    assert (summary["passed"], summary["failed"], summary["skipped"]) == (2, 1, 1)
    assert summary["total_steps"] == 4


def test_a_skipped_step_does_not_count_against_the_success_rate(reporter):
    """
    A step whose `when` was false did not fail. Putting it in the denominator
    would make a workflow look worse the more conditional logic it has.
    """
    _run(reporter, _result("passed"), _result("skipped"), _result("skipped"))

    assert _artifact(reporter, "summary.json")["success_rate"] == 1.0


def test_the_success_rate_is_the_share_of_attempted_steps_that_passed(reporter):
    _run(reporter, _result("passed"), _result("passed"), _result("failed"), _result("skipped"))

    assert _artifact(reporter, "summary.json")["success_rate"] == pytest.approx(2 / 3)


def test_a_run_of_only_skipped_steps_does_not_divide_by_zero(reporter):
    _run(reporter, _result("skipped"), _result("skipped"))

    assert _artifact(reporter, "summary.json")["success_rate"] == 1.0


def test_an_empty_suite_is_written_rather_than_skipped(reporter):
    """A workflow that matched no steps still needs an artifact saying so."""
    _run(reporter)

    summary = _artifact(reporter, "summary.json")
    assert summary["total_steps"] == 0
    assert summary["success_rate"] == 1.0


# ── Step results ──────────────────────────────────────────────────────────────

def test_steps_are_numbered_from_one_in_order(reporter):
    _run(reporter, _result(description="first"), _result(description="second"))

    steps = _artifact(reporter, "results.json")["steps"]
    assert [s["num"] for s in steps] == [1, 2]
    assert [s["description"] for s in steps] == ["first", "second"]


def test_a_step_with_no_description_falls_back_to_its_action(reporter):
    _run(reporter, _result(description=""))

    assert _artifact(reporter, "results.json")["steps"][0]["description"] == "click"


def test_a_skipped_step_carries_its_reason_and_no_error(reporter):
    _run(reporter, _result("skipped", skip_reason="when=false", error="leftover"))

    step = _artifact(reporter, "results.json")["steps"][0]
    assert step["skip_reason"] == "when=false"
    assert step["error"] == ""


def test_a_failed_step_carries_its_error_and_no_skip_reason(reporter):
    _run(reporter, _result("failed", error="boom", skip_reason="leftover"))

    step = _artifact(reporter, "results.json")["steps"][0]
    assert step["error"] == "boom"
    assert step["skip_reason"] == ""


def test_screenshots_are_recorded_by_filename_not_absolute_path(reporter):
    """
    They live beside the report. An absolute path from the machine that ran it
    is meaningless to anyone reading the artifact later.
    """
    _run(reporter, _result(screenshots=["/tmp/run/step_01.png", "/tmp/run/step_02.png"]))

    assert _artifact(reporter, "results.json")["steps"][0]["screenshots"] == [
        "step_01.png", "step_02.png",
    ]


def test_a_single_screenshot_is_recorded_as_a_one_item_list(reporter):
    _run(reporter, _result(screenshot="/tmp/run/only.png"))

    assert _artifact(reporter, "results.json")["steps"][0]["screenshots"] == ["only.png"]


def test_a_step_with_no_screenshot_records_an_empty_list(reporter):
    _run(reporter, _result())

    assert _artifact(reporter, "results.json")["steps"][0]["screenshots"] == []


def test_heal_attempts_appear_only_when_healing_happened(reporter):
    """
    The key is conditional so an ordinary run's results.json is not littered
    with "heal_attempts": 0 on every step.
    """
    _run(reporter, _result("healed", heal_attempts=2), _result("passed"))

    steps = _artifact(reporter, "results.json")["steps"]
    assert steps[0]["heal_attempts"] == 2
    assert "heal_attempts" not in steps[1]


def test_step_output_is_preserved(reporter):
    _run(reporter, _result(output={"books": ["Dune"]}))

    assert _artifact(reporter, "results.json")["steps"][0]["output"] == {"books": ["Dune"]}


def test_confidence_is_rounded_for_readability(reporter):
    _run(reporter, _result(confidence=0.95123456))

    assert _artifact(reporter, "results.json")["steps"][0]["confidence"] == 0.951


# ── Performance ───────────────────────────────────────────────────────────────

def test_the_average_step_duration_ignores_skipped_steps(reporter):
    """
    A skipped step consumed no time. Including it in the denominator would make
    a heavily conditional workflow look faster per step than it is.
    """
    _run(reporter, _result("passed", duration_ms=100), _result("skipped"), _result("skipped"))

    timings = _artifact(reporter, "step_timings.json")
    assert timings["avg_step_duration_ms"] == timings["total_duration_ms"] / 1


def test_a_run_of_only_skipped_steps_reports_a_zero_average(reporter):
    _run(reporter, _result("skipped"))

    assert _artifact(reporter, "step_timings.json")["avg_step_duration_ms"] == 0


def test_every_step_appears_in_the_timings_including_skipped_ones(reporter):
    """
    The average excludes them; the per-step list does not. A reader looking for
    step 2 should find it rather than an off-by-one gap.
    """
    _run(reporter, _result("passed"), _result("skipped"), _result("passed"))

    assert [s["num"] for s in _artifact(reporter, "step_timings.json")["steps"]] == [1, 2, 3]


# ── The cross-test summary ────────────────────────────────────────────────────

def test_finishing_a_suite_refreshes_the_cross_test_summary(reporter, tmp_path):
    _run(reporter, _result("passed"), _result("failed"))

    rollup = json.loads(
        (tmp_path / "reports" / "summary" / "all_tests_summary.json").read_text()
    )
    assert rollup["total_tests"] == 1
    assert rollup["total_passed"] == 1
    assert rollup["total_failed"] == 1


def test_the_returned_message_points_at_the_report(reporter):
    reporter.start_suite("s.json")
    reporter.record_step(_result())

    message = reporter.finish_suite()

    assert str(reporter.manager.current_test_dir) in message
