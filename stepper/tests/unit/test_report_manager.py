"""
TestReportManager — where a run's artifacts end up on disk.

Nothing here decides whether a test passes, which is exactly why it goes
untested and exactly why a defect in it is expensive: it is only noticed when
someone is already debugging something else and finds the evidence missing,
overwritten, or filed under the wrong run.

Two things carry the risk. Test names reach the filesystem, so sanitisation is
a correctness concern rather than a tidiness one — a name with a slash in it
writes outside the run directory. And the cross-test summary reads every
summary.json it can find, so one unreadable file should not take the whole
report with it.
"""
from __future__ import annotations

import json

import pytest

# Imported under an alias: the class is named TestReportManager, and pytest
# tries to collect anything called Test* that it finds in a test module. It has
# an __init__, so collection warns and skips — noise on every run for a class
# that is not a test.
from stepper.engine.reporter.test_report_manager import (
    TestReportManager as ReportManager,
)


@pytest.fixture
def manager(tmp_path) -> ReportManager:
    return ReportManager(str(tmp_path / "reports"))


@pytest.fixture
def started(manager) -> ReportManager:
    manager.create_test_report_dir("ol_smoke_test", 1)
    return manager


# ── Creating a run directory ──────────────────────────────────────────────────

def test_a_run_gets_its_own_directory_with_the_subdirs_it_needs(manager):
    run_dir = manager.create_test_report_dir("ol_smoke_test", 1)

    assert run_dir.is_dir()
    for sub in ("screenshots", "videos", "logs", "attachments"):
        assert (run_dir / sub).is_dir(), f"{sub}/ was not created"


def test_the_run_id_carries_the_date_the_name_and_the_run_number(manager):
    manager.create_test_report_dir("ol_smoke_test", 7)

    test_id = manager.current_test_id
    assert test_id is not None
    assert "ol_smoke_test" in test_id
    assert test_id.endswith("_007"), "run number is zero-padded so runs sort correctly"
    assert test_id[:10].count("-") == 2, "should start with an ISO date"


def test_two_runs_of_the_same_test_do_not_share_a_directory(manager):
    """Run 2 overwriting run 1's evidence is the failure mode here."""
    first = manager.create_test_report_dir("smoke", 1)
    second = manager.create_test_report_dir("smoke", 2)

    assert first != second
    assert first.is_dir() and second.is_dir()


@pytest.mark.parametrize(
    "raw, banned",
    [
        ("Search And Add", " "),
        ("ol/smoke/test", "/"),
    ],
)
def test_a_test_name_is_sanitised_before_it_reaches_the_filesystem(manager, raw, banned):
    """
    A slash in a test name would otherwise create nested directories, or worse,
    write outside the reports tree.
    """
    run_dir = manager.create_test_report_dir(raw, 1)

    assert banned not in run_dir.name
    assert run_dir.parent == manager.reports_base, "the run must stay directly under reports/"


def test_the_name_is_lowercased_so_runs_sort_predictably(manager):
    assert "ol_smoke" in manager.create_test_report_dir("OL_Smoke", 1).name


def test_the_reports_base_is_created_if_it_is_not_there(tmp_path):
    """First run on a fresh checkout has no reports/ directory yet."""
    base = tmp_path / "does" / "not" / "exist"

    ReportManager(str(base))

    assert base.is_dir()


# ── Writing before a run exists ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "call",
    [
        lambda m: m.get_screenshots_dir(),
        lambda m: m.get_logs_dir(),
        lambda m: m.save_metadata({}),
        lambda m: m.save_summary({}),
        lambda m: m.save_step_results([]),
        lambda m: m.save_performance_metrics({}),
        lambda m: m.save_console_log("x"),
    ],
)
def test_writing_before_a_run_directory_exists_fails_loudly(manager, call):
    """
    Silently writing into reports/ root instead would scatter one run's files
    across the tree and leave the next run's summary scan reading them.
    """
    with pytest.raises(RuntimeError, match="No test report directory"):
        call(manager)


# ── The four artifacts ────────────────────────────────────────────────────────

def test_metadata_is_written_and_stamped_with_the_run_id(started):
    started.save_metadata({"browser": "chromium", "headless": True})

    data = json.loads((started.current_test_dir / "metadata.json").read_text())
    assert data["browser"] == "chromium"
    assert data["test_id"] == started.current_test_id
    assert "created_at" in data


def test_the_summary_is_written_and_stamped(started):
    started.save_summary({"passed": 5, "failed": 1})

    data = json.loads((started.current_test_dir / "summary.json").read_text())
    assert data["passed"] == 5
    assert data["test_id"] == started.current_test_id
    assert "finished_at" in data


def test_step_results_are_written_under_a_steps_key(started):
    started.save_step_results([{"action": "click", "status": "passed"}])

    data = json.loads((started.current_test_dir / "results.json").read_text())
    assert data["steps"][0]["action"] == "click"
    assert data["test_id"] == started.current_test_id


def test_performance_metrics_land_in_step_timings(started):
    started.save_performance_metrics({"total_ms": 1234})

    data = json.loads((started.current_test_dir / "step_timings.json").read_text())
    assert data["total_ms"] == 1234
    assert "recorded_at" in data


def test_a_value_json_cannot_serialise_does_not_lose_the_whole_report(started):
    """
    `default=str` is there so one exotic value degrades to its repr instead of
    raising and discarding every artifact for the run.
    """
    from datetime import datetime

    started.save_metadata({"started": datetime(2026, 1, 1, 12, 0, 0)})

    data = json.loads((started.current_test_dir / "metadata.json").read_text())
    assert "2026-01-01" in data["started"]


def test_unicode_survives_the_round_trip(started):
    started.save_step_results([{"title": "Dune — Frank Herbert"}])

    data = json.loads((started.current_test_dir / "results.json").read_text())
    assert data["steps"][0]["title"] == "Dune — Frank Herbert"


# ── Screenshots and logs ──────────────────────────────────────────────────────

def test_a_screenshot_is_copied_in_with_an_ordered_name(started, tmp_path):
    source = tmp_path / "shot.png"
    source.write_bytes(b"\x89PNG fake")

    dest = started.copy_screenshot(source, "Click Login", 3)

    assert dest.name == "03_click_login.png", "zero-padded so files sort by step order"
    assert dest.read_bytes() == b"\x89PNG fake"
    assert dest.parent == started.get_screenshots_dir()


def test_copying_a_screenshot_that_is_not_there_does_not_raise(started, tmp_path):
    """
    A step can fail before its screenshot is written. Losing the run's remaining
    artifacts because the evidence for one step is missing would be worse.
    """
    dest = started.copy_screenshot(tmp_path / "missing.png", "step", 1)

    assert not dest.exists()


def test_a_console_log_is_written_into_the_run_s_logs_dir(started):
    path = started.save_console_log("line one\nline two")

    assert path.parent == started.get_logs_dir()
    assert path.read_text() == "line one\nline two"


# ── The cross-test summary ────────────────────────────────────────────────────

def _finished_run(manager, name: str, run: int, passed: int, failed: int) -> None:
    manager.create_test_report_dir(name, run)
    manager.save_summary({"passed": passed, "failed": failed, "name": name})


def test_the_cross_test_summary_totals_every_run(manager):
    _finished_run(manager, "a", 1, passed=3, failed=1)
    _finished_run(manager, "b", 1, passed=2, failed=0)

    data = json.loads(manager.generate_cross_test_summary().read_text())

    assert data["total_tests"] == 2
    assert data["total_passed"] == 5
    assert data["total_failed"] == 1
    assert data["success_rate"] == pytest.approx(5 / 6)


def test_a_run_with_no_summary_yet_is_skipped_not_counted(manager):
    """
    A run that crashed before writing summary.json leaves a directory behind.
    Counting it as a zero-step pass would inflate the success rate.
    """
    _finished_run(manager, "finished", 1, passed=1, failed=0)
    manager.create_test_report_dir("crashed", 1)   # no summary written

    data = json.loads(manager.generate_cross_test_summary().read_text())

    assert data["total_tests"] == 1


def test_an_empty_reports_tree_reports_full_success_rather_than_dividing_by_zero(manager):
    data = json.loads(manager.generate_cross_test_summary().read_text())

    assert data["total_tests"] == 0
    assert data["success_rate"] == 1.0


def test_the_summary_directory_is_not_scanned_as_a_test_run(manager):
    """
    generate_cross_test_summary writes into reports/summary/. If that directory
    matched the run glob, each call would fold the previous summary into the
    next one.
    """
    _finished_run(manager, "a", 1, passed=1, failed=0)

    manager.generate_cross_test_summary()
    data = json.loads(manager.generate_cross_test_summary().read_text())

    assert data["total_tests"] == 1, "the summary directory was scanned as a run"


def test_unrelated_directories_are_not_scanned_as_runs(manager):
    """The glob is date-shaped for a reason — allure-results lives here too."""
    _finished_run(manager, "a", 1, passed=1, failed=0)
    (manager.reports_base / "allure-results").mkdir()
    (manager.reports_base / "allure-results" / "summary.json").write_text('{"passed": 99}')

    data = json.loads(manager.generate_cross_test_summary().read_text())

    assert data["total_passed"] == 1
