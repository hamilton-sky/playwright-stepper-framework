"""
Tests for RunConfig and the browser-free assembly helpers in main.py.

RunConfig owns the derivations that used to be recomputed inline in run() —
site name, run label, artifact paths, whether the site persists a session — so
they are worth pinning directly. resolve_screenshots_dir is here too because
its fallback used to send every site's screenshots to OpenLibrary.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from main import RunConfig, resolve_screenshots_dir


# ── Construction ──────────────────────────────────────────────────────────────

def test_requires_a_workflow_or_a_task():
    with pytest.raises(ValueError, match="Provide --workflow or --task"):
        RunConfig()


def test_is_immutable():
    cfg = RunConfig(task="do a thing")
    with pytest.raises(Exception):
        cfg.headless = False        # type: ignore[misc]


def test_defaults_are_the_conservative_ones():
    cfg = RunConfig(task="anything")
    assert cfg.headless is True
    assert cfg.max_heal_attempts == 0
    assert cfg.shadow is False
    assert cfg.ci is False
    assert cfg.record_video is False


# ── Site derivation ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("stepper/sites/saucedemo/workflows/sd_happy_path.json", "saucedemo"),
    ("stepper/sites/openlibrary/workflows/ol_smoke_test.json", "openlibrary"),
    ("/abs/stepper/sites/phptravels/workflows/hotel_booking.json", "phptravels"),
])
def test_site_comes_from_the_workflow_path(path, expected):
    assert RunConfig(workflow_path=path).site == expected


def test_site_is_shared_for_a_natural_language_task():
    assert RunConfig(task="search Dune").site == "shared"


def test_site_is_shared_for_a_workflow_outside_a_sites_directory():
    assert RunConfig(workflow_path="/tmp/scratch/my_flow.json").site == "shared"


# ── Labels and paths ──────────────────────────────────────────────────────────

def test_run_label_is_the_workflow_stem():
    cfg = RunConfig(workflow_path="stepper/sites/saucedemo/workflows/sd_happy_path.json")
    assert cfg.run_label == "sd_happy_path"


def test_run_label_for_a_task_is_task():
    assert RunConfig(task="search Dune").run_label == "task"


def test_suite_name_prefers_the_workflow_path():
    assert RunConfig(workflow_path="a/b.json").suite_name == "a/b.json"
    assert RunConfig(task="search Dune").suite_name == "search Dune"


def test_base_dir_is_the_workflow_directory():
    cfg = RunConfig(workflow_path="stepper/sites/saucedemo/workflows/sd_happy_path.json")
    assert cfg.base_dir == Path("stepper/sites/saucedemo/workflows")


def test_base_dir_for_a_task_is_the_cwd():
    assert RunConfig(task="search Dune").base_dir == Path.cwd()


def test_artifact_path_lands_in_the_runs_own_site():
    cfg = RunConfig(workflow_path="stepper/sites/saucedemo/workflows/sd_happy_path.json")
    assert cfg.artifact_path("heal_cache.json").parts[-4:] == (
        "sites", "saucedemo", "artifacts", "heal_cache.json"
    )


# ── Session persistence ───────────────────────────────────────────────────────

def test_openlibrary_persists_its_session():
    cfg = RunConfig(workflow_path="stepper/sites/openlibrary/workflows/ol_smoke_test.json")
    assert cfg.storage_state_path is not None
    assert cfg.storage_state_path.name == "storage_state.json"
    assert "openlibrary" in cfg.storage_state_path.parts


@pytest.mark.parametrize("path", [
    "stepper/sites/saucedemo/workflows/sd_happy_path.json",
    "stepper/sites/phptravels/workflows/hotel_booking.json",
])
def test_other_sites_log_in_fresh_each_run(path):
    assert RunConfig(workflow_path=path).storage_state_path is None


def test_a_task_has_no_session_to_persist():
    assert RunConfig(task="search Dune").storage_state_path is None


# ── Screenshot directory ──────────────────────────────────────────────────────

def _reporter_with_dir(tmp_path):
    shots = tmp_path / "screenshots"
    return SimpleNamespace(manager=SimpleNamespace(
        current_test_dir=tmp_path,
        get_screenshots_dir=lambda: shots,
    )), shots


def test_screenshots_go_to_the_per_test_report_dir_when_there_is_one(tmp_path):
    cfg = RunConfig(workflow_path="stepper/sites/saucedemo/workflows/sd_happy_path.json")
    reporter, shots = _reporter_with_dir(tmp_path)

    assert resolve_screenshots_dir(cfg, reporter) == shots


def test_screenshot_fallback_uses_the_runs_own_site_not_openlibrary():
    """Regression: the fallback was hardcoded to openlibrary for every site."""
    cfg = RunConfig(workflow_path="stepper/sites/saucedemo/workflows/sd_happy_path.json")

    fallback = resolve_screenshots_dir(cfg, None)

    assert fallback.parts[-3:] == ("saucedemo", "artifacts", "screenshots")
    assert "openlibrary" not in fallback.parts


def test_screenshot_fallback_when_the_reporter_has_no_test_dir():
    cfg = RunConfig(workflow_path="stepper/sites/phptravels/workflows/hotel_booking.json")
    reporter = SimpleNamespace(manager=SimpleNamespace(current_test_dir=None))

    assert resolve_screenshots_dir(cfg, reporter).parts[-3:] == (
        "phptravels", "artifacts", "screenshots"
    )


# ── Healer construction ───────────────────────────────────────────────────────

def test_no_healer_when_healing_was_not_requested():
    cfg = RunConfig(task="anything", max_heal_attempts=0)
    assert main.build_healer(cfg, registry=object()) is None


def test_no_healer_without_a_provider_key(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    cfg = RunConfig(task="anything", max_heal_attempts=2)

    assert main.build_healer(cfg, registry=object()) is None
