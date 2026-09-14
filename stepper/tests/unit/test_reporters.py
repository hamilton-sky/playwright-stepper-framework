"""
The reporter strategies — what a run leaves behind after the browser closes.

These are the artifacts a failing CI run is read through. If a status is
mis-mapped or a screenshot is not attached, nobody notices at the time: the run
still passes or fails correctly, and the damage shows up later, when someone is
trying to work out what happened from a report that quietly lied.

Everything here writes to tmp_path. No browser, no network.
"""
from __future__ import annotations

import json

import pytest

from stepper.engine.interfaces import StepConfig, StepResult
from stepper.engine.reporter.reporters import (
    AllureReporter,
    CompositeReporter,
    ConsoleReporter,
    JsonReporter,
)


def _result(status="passed", description="do the thing", **kw) -> StepResult:
    return StepResult(
        step=StepConfig(action="click", description=description),
        status=status,
        **kw,
    )


# ── ConsoleReporter ───────────────────────────────────────────────────────────

def test_the_console_summary_counts_what_happened(capsys):
    reporter = ConsoleReporter()
    reporter.start_suite("my suite")
    reporter.record_step(_result("passed"))
    reporter.record_step(_result("failed"))
    reporter.record_step(_result("passed"))

    summary = reporter.finish_suite()

    assert summary == "2/3 passed"
    assert "1 failed" in capsys.readouterr().out


def test_an_error_is_printed_under_its_step(capsys):
    reporter = ConsoleReporter()
    reporter.start_suite("s")
    reporter.record_step(_result("failed", error="Timeout 5000ms exceeded"))
    reporter.finish_suite()

    assert "Timeout 5000ms exceeded" in capsys.readouterr().out


def test_a_step_with_no_description_falls_back_to_its_action(capsys):
    reporter = ConsoleReporter()
    reporter.start_suite("s")
    reporter.record_step(_result(description=""))
    reporter.finish_suite()

    assert "click" in capsys.readouterr().out


def test_starting_a_second_suite_does_not_carry_the_first_one_s_results(capsys):
    """
    The data-driven runner reuses one reporter across rows. Leaking results
    between them would make row 2 report row 1's failures as its own.
    """
    reporter = ConsoleReporter()
    reporter.start_suite("first")
    reporter.record_step(_result("failed"))

    reporter.start_suite("second")
    reporter.record_step(_result("passed"))

    assert reporter.finish_suite() == "1/1 passed"


def test_unicode_in_an_error_does_not_crash_the_console(capsys):
    """
    _safe_print exists because Windows consoles reject non-ASCII. A reporter
    that raises while reporting loses the whole run's output.
    """
    reporter = ConsoleReporter()
    reporter.start_suite("s")
    reporter.record_step(_result("failed", error="login failed — unknown error ✗"))

    reporter.finish_suite()   # must not raise


# ── JsonReporter ──────────────────────────────────────────────────────────────

def test_the_json_report_lands_on_disk_with_the_step_detail(tmp_path):
    path = tmp_path / "report.json"
    reporter = JsonReporter(str(path))
    reporter.start_suite("my suite")
    reporter.record_step(_result("passed", confidence=0.9512))
    reporter.record_step(_result("failed", error="boom"))

    reporter.finish_suite()

    report = json.loads(path.read_text())
    assert report["suite"] == "my suite"
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert [s["status"] for s in report["steps"]] == ["passed", "failed"]
    assert report["steps"][0]["confidence"] == 0.951, "confidence is rounded for readability"


def test_a_skipped_step_reports_its_reason_and_not_an_error(tmp_path):
    """
    A skip is not a failure. Putting the skip reason in `error` would make a
    conditional step that correctly did not run look like something went wrong.
    """
    path = tmp_path / "r.json"
    reporter = JsonReporter(str(path))
    reporter.start_suite("s")
    reporter.record_step(_result("skipped", skip_reason="when=false", error="ignored"))
    reporter.finish_suite()

    step = json.loads(path.read_text())["steps"][0]
    assert step["skip_reason"] == "when=false"
    assert step["error"] == ""


def test_a_failed_step_reports_its_error_and_not_a_skip_reason(tmp_path):
    path = tmp_path / "r.json"
    reporter = JsonReporter(str(path))
    reporter.start_suite("s")
    reporter.record_step(_result("failed", error="boom", skip_reason="stale"))
    reporter.finish_suite()

    step = json.loads(path.read_text())["steps"][0]
    assert step["error"] == "boom"
    assert step["skip_reason"] == ""


def test_the_json_report_is_valid_json_when_a_step_output_carries_unicode(tmp_path):
    path = tmp_path / "r.json"
    reporter = JsonReporter(str(path))
    reporter.start_suite("s")
    reporter.record_step(_result("passed", output={"title": "Dune — Frank Herbert"}))
    reporter.finish_suite()

    assert json.loads(path.read_text())["steps"][0]["output"]["title"] == "Dune — Frank Herbert"


def test_a_suite_with_no_steps_still_writes_a_report(tmp_path):
    """A run that died before step 1 still needs an artifact saying so."""
    path = tmp_path / "r.json"
    reporter = JsonReporter(str(path))
    reporter.start_suite("s")

    reporter.finish_suite()

    assert json.loads(path.read_text())["steps"] == []


# ── AllureReporter ────────────────────────────────────────────────────────────

def _allure_output(tmp_path) -> dict:
    files = list(tmp_path.glob("*-result.json"))
    assert len(files) == 1, f"expected one allure result, found {len(files)}"
    return json.loads(files[0].read_text())


def test_the_allure_container_records_each_step(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("sd_smoke_test.json")
    reporter.record_step(_result("passed", description="log in"))
    reporter.record_step(_result("failed", description="check cart", error="boom"))
    reporter.finish_suite()

    container = _allure_output(tmp_path)
    assert container["name"] == "sd_smoke_test", "the .json suffix is stripped for the suite name"
    assert [s["name"] for s in container["steps"]] == ["log in", "check cart"]
    assert container["steps"][1]["statusDetails"]["message"] == "boom"


@pytest.mark.parametrize(
    "status, allure_status",
    [("passed", "passed"), ("failed", "failed"), ("skipped", "skipped"), ("warned", "broken")],
)
def test_each_status_maps_to_its_allure_equivalent(tmp_path, status, allure_status):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result(status))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["steps"][0]["status"] == allure_status


def test_a_healed_step_is_not_reported_as_unknown(tmp_path):
    """
    Healing is the framework's headline feature, and "healed" is a status
    StepRunner really produces. It was missing from STATUS_MAP, so every healed
    step landed in an Allure report as "unknown" — the one status that tells a
    reader nothing at all about whether the step worked.

    It did work: a heal that is applied and asserted leaves a passing step.
    """
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result("healed"))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["steps"][0]["status"] != "unknown"


def test_the_overall_status_is_failed_when_any_step_failed(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result("passed"))
    reporter.record_step(_result("failed"))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["status"] == "failed"


def test_a_warning_alone_makes_the_suite_broken_not_failed(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result("passed"))
    reporter.record_step(_result("warned"))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["status"] == "broken"


def test_a_failure_outranks_a_warning(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result("warned"))
    reporter.record_step(_result("failed"))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["status"] == "failed"


def test_every_screenshot_from_a_multi_shot_step_is_attached(tmp_path):
    """
    for_each_item produces one screenshot per iteration. Attaching only the
    first would drop the evidence for every iteration after it.
    """
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result(screenshots=["/a/one.png", "/a/two.png", "/a/three.png"]))
    reporter.finish_suite()

    attachments = _allure_output(tmp_path)["steps"][0]["attachments"]
    assert [a["source"] for a in attachments] == ["one.png", "two.png", "three.png"]
    assert all(a["type"] == "image/png" for a in attachments)


def test_a_single_screenshot_is_attached_when_there_is_no_list(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result(screenshot="/a/only.png"))
    reporter.finish_suite()

    assert _allure_output(tmp_path)["steps"][0]["attachments"][0]["source"] == "only.png"


def test_the_list_wins_when_a_step_carries_both(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result(screenshot="/a/single.png", screenshots=["/a/1.png", "/a/2.png"]))
    reporter.finish_suite()

    sources = [a["source"] for a in _allure_output(tmp_path)["steps"][0]["attachments"]]
    assert sources == ["1.png", "2.png"]


def test_a_step_with_no_screenshot_gets_no_attachments_key(tmp_path):
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    reporter.record_step(_result())
    reporter.finish_suite()

    assert "attachments" not in _allure_output(tmp_path)["steps"][0]


def test_step_timings_do_not_overlap(tmp_path):
    """Allure renders these as a timeline; overlapping spans draw nonsense."""
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")
    for _ in range(3):
        reporter.record_step(_result())
    reporter.finish_suite()

    steps = _allure_output(tmp_path)["steps"]
    for earlier, later in zip(steps, steps[1:]):
        assert earlier["stop"] <= later["start"]


def test_a_suite_with_no_steps_does_not_divide_by_zero(tmp_path):
    """step_duration divides by len(results); an empty run must not explode."""
    reporter = AllureReporter(str(tmp_path))
    reporter.start_suite("s")

    reporter.finish_suite()   # must not raise

    assert _allure_output(tmp_path)["steps"] == []


# ── CompositeReporter ─────────────────────────────────────────────────────────

def test_the_composite_broadcasts_every_call(tmp_path):
    json_path = tmp_path / "r.json"
    composite = CompositeReporter([ConsoleReporter(), JsonReporter(str(json_path))])

    composite.start_suite("s")
    composite.record_step(_result("passed"))
    summary = composite.finish_suite()

    assert json_path.exists(), "the wrapped JsonReporter never wrote"
    assert "1/1 passed" in summary
    assert str(json_path) in summary


def test_an_empty_composite_is_harmless():
    composite = CompositeReporter([])

    composite.start_suite("s")
    composite.record_step(_result())

    assert composite.finish_suite() == ""
