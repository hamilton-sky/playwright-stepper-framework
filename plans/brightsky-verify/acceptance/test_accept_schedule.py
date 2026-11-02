"""
brightsky-verify acceptance: the scheduled GitHub Actions workflow.

Source: spec.md, story "Run on a schedule" and the Edge cases row "The
scheduled job without secrets". map.md: secrets cannot be read in `if:`
directly, so they are mapped to `env`; PyYAML reads the `on:` key as True.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "brightsky-verify.yml"
_VERIFY = re.compile(r"python3?\s+-m\s+stepper\s+brightsky\s+verify\s+--all-unverified")


def _load() -> dict:
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} does not exist"
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps_with_env(data: dict):
    """(job, step, merged env) for every step, workflow env < job env < step env."""
    out = []
    for job in (data.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            env = {}
            env.update(data.get("env") or {})
            env.update(job.get("env") or {})
            env.update(step.get("env") or {})
            out.append((job, step, env))
    return out


def _verify_step(data: dict):
    found = [(job, step, env) for job, step, env in _steps_with_env(data)
             if _VERIFY.search(str(step.get("run", "")))]
    assert len(found) == 1, "expected one step running brightsky verify --all-unverified"
    return found[0]


# Story: `.github/workflows/brightsky-verify.yml` runs on a daily `schedule` and
#        on `workflow_dispatch`.
def test_the_workflow_runs_daily_and_on_dispatch():
    data = _load()
    on = data.get("on", data.get(True))

    assert isinstance(on, dict)
    assert "workflow_dispatch" in on
    schedule = on.get("schedule")
    assert isinstance(schedule, list) and schedule
    for entry in schedule:
        fields = str(entry["cron"]).split()
        assert len(fields) == 5
        minute, hour, day, month, weekday = fields
        assert (day, month, weekday) == ("*", "*", "*"), "the schedule must be daily"
        assert "*" not in (minute, hour) and "/" not in minute + hour


# Story: It runs `python -m stepper brightsky verify --all-unverified` headless,
#        with `BRIGHTSKY_API_URL` and `BRIGHTSKY_BRIDGE_TOKEN` taken from repo secrets.
def test_the_job_verifies_the_queue_headless_with_the_secrets():
    _, step, env = _verify_step(_load())

    assert "--show" not in str(step["run"])
    for name in ("BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"):
        assert re.search(r"\$\{\{\s*secrets\." + name + r"\s*\}\}", str(env.get(name, ""))), \
            f"{name} is not taken from secrets.{name}"


# Story: When either secret is unset, the job emits a `::notice` that names both
#        secrets, skips every later step, and ends green.
# Edge: The scheduled job without secrets | a `::notice`, later steps skipped, job green
def test_without_secrets_the_job_notices_and_skips_the_rest():
    data = _load()
    job, verify_step, _ = _verify_step(data)
    steps = job["steps"]

    notices = [i for i, s in enumerate(steps) if "::notice" in str(s.get("run", ""))]
    assert notices, "no step emits a ::notice"
    i = notices[0]
    notice = steps[i]
    assert "BRIGHTSKY_API_URL" in str(notice["run"])
    assert "BRIGHTSKY_BRIDGE_TOKEN" in str(notice["run"])
    assert not re.search(r"\bexit\s+[1-9]", str(notice["run"])), "the skip must end green"

    later = steps[i + 1:]
    assert verify_step in later
    for step in later:
        assert "if" in step, f"step {step.get('name') or step.get('run')!r} is not skipped"
