"""
Preflight — a domain saying what it is missing, before anything opens.

M5's second half, and the answer to the last open question in
docs/mixed-domain-plan.md §9: a workflow naming a domain whose environment is
incomplete should fail at plan time with the domain named, not at first use.

Two rules carry the risk, and they pull in opposite directions.

**A false "not ready" blocks a run that would have worked.** `run` refuses on a
preflight failure, so every uncertain case in the browser check must report
nothing. The tests below pin the silences as hard as the failures — a check
that guesses is worse than the late failure it replaces.

**validate and run take different postures on the same fact.** A plan is
well-formed or it is not, and that does not depend on the machine asking;
whether this machine has a browser does. So `validate` reports an unready
domain and still exits 0, while `run` refuses. Collapsing the two would turn
CI's deliberate missing-credentials skip into a red build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stepper.bootstrap.infra import browser_preflight, _browsers_root
from stepper.bootstrap.session import (Domain, DomainNotReadyError, get_domain,
                                       no_preflight, web_preflight)
from stepper.engine.session import NullSession


# ── The default ───────────────────────────────────────────────────────────────

def test_a_domain_with_no_preflight_is_always_ready():
    assert no_preflight() == []
    assert no_preflight(object(), object()) == []


def test_preflight_defaults_to_no_preflight_on_a_new_domain():
    """
    Every domain predating M5 was constructed without one. Defaulting to
    "ready" keeps them working; defaulting to "not ready" would have stopped
    every existing run at plan time.
    """
    assert Domain(name="x", session=NullSession).preflight is no_preflight


def test_the_noop_domain_needs_nothing(registered_sites):
    """NullSession opens a bare object — there is nothing that could be absent."""
    assert get_domain("noop").preflight(None, None) == []


# ── The browser check: what it reports ────────────────────────────────────────

class _Settings:
    def __init__(self, browser):
        self.browser = browser


def _playwright_installed() -> bool:
    try:
        import playwright                                              # noqa: F401
    except ImportError:
        return False
    return True


#: These read Playwright's own browsers.json to learn which build it insists
#: on. With the package absent the check correctly short-circuits to "playwright
#: is not installed" — a different answer, and one its own test already pins.
needs_playwright = pytest.mark.skipif(
    not _playwright_installed(),
    reason="reads the revision out of Playwright's browsers.json",
)


@needs_playwright
def test_a_browser_that_is_not_installed_is_reported():
    """
    firefox is not in this image. The message has to name the revision, since
    "firefox is missing" and "the wrong firefox build is present" need
    different fixes.
    """
    reasons = browser_preflight("firefox")

    assert len(reasons) == 1
    assert "firefox" in reasons[0]
    assert "playwright install firefox" in reasons[0]


@needs_playwright
def test_the_installed_browser_passes():
    assert browser_preflight("chromium") == []


@needs_playwright
def test_web_preflight_reads_the_browser_off_settings():
    assert web_preflight(None, _Settings("chromium")) == []
    assert web_preflight(None, _Settings("firefox")) != []


def test_web_preflight_assumes_chromium_when_settings_say_nothing():
    """
    plan_report may be called with settings that predate a browser field, and
    chromium is what launch_browser falls back to.
    """
    assert web_preflight(None, None) == browser_preflight("chromium")


# ── The browser check: what it deliberately stays quiet about ─────────────────

@needs_playwright
def test_an_executable_override_that_exists_silences_the_check(monkeypatch, tmp_path):
    """
    BROWSER_EXECUTABLE_PATH is the documented escape hatch for an image whose
    chromium revision differs from the pinned one. Pointing it at a binary is
    exactly the case where the revision on disk is *expected* not to match, so
    the check must defer to it rather than contradict it.
    """
    binary = tmp_path / "chromium"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("BROWSER_EXECUTABLE_PATH", str(binary))

    assert browser_preflight("firefox") == []


@needs_playwright
def test_an_override_pointing_nowhere_does_not_silence_the_check(monkeypatch):
    """
    browser_launch_kwargs ignores a stale path with a warning and falls back to
    Playwright's own browser, so the revision on disk is what will actually be
    used and is worth checking. Treating the stale path itself as the failure
    would contradict that deliberate fallback.
    """
    monkeypatch.setenv("BROWSER_EXECUTABLE_PATH", "/nowhere/at/all/chromium")

    assert browser_preflight("firefox") != []
    assert browser_preflight("chromium") == []


@needs_playwright
def test_a_browser_with_per_platform_revisions_is_not_judged():
    """
    webkit carries revisionOverrides, so the wanted revision depends on the
    platform. Re-deriving Playwright's own resolution here would be a guess,
    and a wrong guess blocks a run.
    """
    assert browser_preflight("webkit") == []


@needs_playwright
def test_an_unknown_browser_name_is_not_judged():
    assert browser_preflight("netscape") == []


@needs_playwright
def test_browsers_installed_beside_the_package_are_not_judged(monkeypatch):
    """PLAYWRIGHT_BROWSERS_PATH=0 uses a layout this check does not model."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")

    assert _browsers_root() is None
    assert browser_preflight("firefox") == []


def test_a_missing_playwright_is_reported(monkeypatch):
    """
    A None in sys.modules is what CPython treats as "this import fails" — the
    same ImportError a machine without the package raises.
    """
    monkeypatch.setitem(sys.modules, "playwright", None)

    reasons = browser_preflight("chromium")

    assert len(reasons) == 1 and "playwright is not installed" in reasons[0]


@needs_playwright
def test_an_unreadable_manifest_is_not_judged(monkeypatch, tmp_path):
    """Any uncertainty reports nothing — including a Playwright layout change."""
    import stepper.bootstrap.infra as infra

    def _broken(*a, **kw):
        raise ValueError("browsers.json is not what it used to be")

    monkeypatch.setattr(infra.json, "loads", _broken)

    assert browser_preflight("chromium") == []


def test_the_browsers_root_follows_the_environment(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/somewhere/else")

    assert _browsers_root() == Path("/somewhere/else")


# ── Asking every domain a run will use ────────────────────────────────────────

from stepper.main import PlanReport, RunConfig, plan_report, preflight_domains  # noqa: E402


def test_every_domain_is_asked_and_only_the_unready_are_reported(monkeypatch):
    import stepper.main as main

    domains = {
        "ok":  Domain(name="ok", session=NullSession),
        "bad": Domain(name="bad", session=NullSession,
                      preflight=lambda cfg, settings: ["no credentials"]),
    }
    monkeypatch.setattr(main, "get_domain", domains.__getitem__)

    assert preflight_domains(None, None, ["ok", "bad"]) == {"bad": ["no credentials"]}


def test_a_preflight_that_raises_is_reported_not_propagated(monkeypatch):
    """
    One domain's broken check must not stop the others being asked, and
    `validate` walking 17 workflows must not die on the first.
    """
    import stepper.main as main

    def boom(cfg, settings):
        raise RuntimeError("the check itself is broken")

    monkeypatch.setattr(main, "get_domain", lambda name: Domain(
        name=name, session=NullSession, preflight=boom))

    missing = preflight_domains(None, None, ["web"])

    assert "RuntimeError" in missing["web"][0]
    assert "the check itself is broken" in missing["web"][0]


def test_every_reason_from_one_domain_is_kept(monkeypatch):
    """All errors at once — the same principle PlanValidator is built on."""
    import stepper.main as main

    monkeypatch.setattr(main, "get_domain", lambda name: Domain(
        name=name, session=NullSession,
        preflight=lambda cfg, settings: ["no host", "no password"]))

    assert preflight_domains(None, None, ["db"]) == {"db": ["no host", "no password"]}


# ── The two postures ──────────────────────────────────────────────────────────

_WEB_WORKFLOW = "stepper/sites/saucedemo/workflows/sd_smoke_test.json"

#: prepare_run builds a real ElementResolver when not given one, and the unit
#: suite refuses to load the embedding model behind it. Nothing here resolves
#: an element, so any object will do.
_STUB_RESOLVER = object()


@pytest.fixture
def registered_sites():
    """
    Domains register when their site does, and sites register when an action
    registry is built. Without this a test asking for the noop domain passes or
    fails on whether some earlier test happened to build one.
    """
    from stepper.bootstrap.infra import register_all_sites
    import stepper.main as main
    from stepper.engine.actions.factory import ActionRegistry

    register_all_sites(ActionRegistry(), main._stepper_root)


@needs_playwright
def test_plan_report_names_the_domains_a_workflow_opens():
    report = plan_report(RunConfig(workflow_path=_WEB_WORKFLOW))

    assert report.domains == ["web"]
    assert report.ready and report.missing == {}
    assert len(report.steps) > 0


def test_the_primary_domain_is_listed_even_when_no_step_names_it():
    """
    build_pipeline opens the primary eagerly — for a web run that is the moment
    the browser launches — so it is a domain this run opens whatever the steps
    say.
    """
    report = plan_report(RunConfig(workflow_path="stepper/sites/_noop/workflows/noop_smoke.json"))

    assert "noop" in report.domains


def test_a_plan_report_is_not_made_unready_by_a_bad_plan():
    assert PlanReport(steps=[], domains=["web"], missing={}).ready is True
    assert PlanReport(steps=[], domains=["web"], missing={"web": ["x"]}).ready is False


def test_validate_reports_an_unready_domain_without_calling_the_plan_invalid(monkeypatch):
    """
    The posture split. A missing browser does not make the JSON malformed, and
    CI runs `validate` on machines that legitimately lack one.
    """
    import stepper.main as main
    monkeypatch.setattr(main, "preflight_domains",
                        lambda cfg, settings, domains: {"web": ["no browser"]})

    report = plan_report(RunConfig(workflow_path=_WEB_WORKFLOW))

    assert report.missing == {"web": ["no browser"]}
    assert not report.ready
    assert len(report.steps) > 0, "the plan itself is still valid and returned"


def test_run_refuses_to_prepare_when_a_domain_is_not_ready(monkeypatch):
    import stepper.main as main
    monkeypatch.setattr(main, "preflight_domains",
                        lambda cfg, settings, domains: {"web": ["no browser"]})

    with pytest.raises(DomainNotReadyError) as exc:
        main.prepare_run(RunConfig(workflow_path=_WEB_WORKFLOW), resolver=_STUB_RESOLVER)

    assert "web" in str(exc.value) and "no browser" in str(exc.value)
    assert exc.value.missing == {"web": ["no browser"]}


@needs_playwright
def test_a_ready_run_still_prepares(monkeypatch):
    import stepper.main as main
    prepared = main.prepare_run(RunConfig(workflow_path=_WEB_WORKFLOW),
                                resolver=_STUB_RESOLVER)

    assert prepared.domains == ["web"]
    assert prepared.steps
