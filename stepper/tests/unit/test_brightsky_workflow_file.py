"""
.github/workflows/brightsky-verify.yml: the daily GitHub Actions job that walks
the BrightSky verification queue.

The job reads the two BrightSky secrets through its env (secrets cannot be
tested in `if:` directly), skips every later step with a `::notice` when either
is unset, and never expands `${{ secrets.* }}` into a shell command.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "brightsky-verify.yml"
_GATE = "steps.secrets.outputs.available"


def _load() -> dict:
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} does not exist"
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _job(data: dict) -> dict:
    jobs = data.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1, "expected exactly one job"
    (job,) = jobs.values()
    return job


# ── triggers ──────────────────────────────────────────────────────────────────

def test_triggers_are_schedule_and_workflow_dispatch():
    # YAML 1.1 reads the plain key `on` as boolean True.
    data = _load()
    on = data.get("on", data.get(True))

    assert isinstance(on, dict)
    assert "workflow_dispatch" in on
    schedule = on.get("schedule")
    assert isinstance(schedule, list) and len(schedule) == 1
    assert len(str(schedule[0]["cron"]).split()) == 5


# ── job settings ──────────────────────────────────────────────────────────────

def test_job_has_read_only_permissions_and_a_timeout():
    data = _load()
    job = _job(data)
    permissions = job.get("permissions", data.get("permissions"))

    assert permissions == {"contents": "read"}
    assert isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] > 0
    assert job.get("concurrency") or data.get("concurrency")


def test_job_env_maps_both_brightsky_secrets():
    env = _job(_load()).get("env") or {}

    for name in ("BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"):
        assert env.get(name) == "${{ secrets.%s }}" % name


# ── steps ─────────────────────────────────────────────────────────────────────

def test_first_step_detects_the_secrets_and_emits_a_notice():
    first = _job(_load())["steps"][0]

    assert first.get("id") == "secrets"
    assert "::notice" in str(first.get("run", ""))
    assert "if" not in first


def test_every_later_step_is_gated_on_the_secrets_step():
    later = _job(_load())["steps"][1:]

    assert later
    for step in later:
        assert _GATE in str(step.get("if", "")), f"step {step.get('name')!r} is not gated"


def test_some_step_runs_the_verification_queue():
    runs = [str(step.get("run", "")) for step in _job(_load())["steps"]]

    assert any("brightsky verify --all-unverified" in run for run in runs)


def test_no_run_script_interpolates_secrets():
    for step in _job(_load())["steps"]:
        assert "secrets." not in str(step.get("run", "")), f"step {step.get('name')!r}"
