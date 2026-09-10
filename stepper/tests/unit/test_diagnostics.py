"""
log_swallowed — the three visibility levels, and that it never breaks its caller.

The framework swallows exceptions on purpose in ~139 places, and it should:
the resolver cascade depends on every strategy being allowed to shrug. What it
must not do is make a code defect look like an ordinary miss, which is how
BookDetailPage's None-behaviour bug survived — an AttributeError inside a
try/except that returned False, logged as "the strategy failed".
"""
from __future__ import annotations

import logging

import pytest

from poms.shared.diagnostics import debug_enabled, log_swallowed


@pytest.fixture
def caplog_at_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="stepper.swallowed")
    return caplog


@pytest.fixture(autouse=True)
def no_debug_env(monkeypatch):
    monkeypatch.delenv("STEPPER_DEBUG", raising=False)


# ── Quiet by default ──────────────────────────────────────────────────────────

def test_an_ordinary_exception_is_debug_only(caplog_at_debug):
    log_swallowed("SomeResolver.collect", TimeoutError("element never appeared"))

    record = caplog_at_debug.records[-1]
    assert record.levelno == logging.DEBUG
    assert "SomeResolver.collect" in record.getMessage()


def test_an_ordinary_exception_is_invisible_at_the_console_level(caplog):
    """INFO is the console default, so a routine miss must not appear there."""
    caplog.set_level(logging.INFO, logger="stepper.swallowed")

    log_swallowed("SomeResolver.collect", TimeoutError("nope"))

    assert caplog.records == []


# ── Bug-shaped exceptions always warn ─────────────────────────────────────────

@pytest.mark.parametrize("exc", [
    AttributeError("'NoneType' object has no attribute 'hover_before_click'"),
    NameError("name 'foo' is not defined"),
    TypeError("'int' object is not iterable"),
    ImportError("no module named 'nope'"),
])
def test_a_code_defect_warns_without_the_env_var(exc, caplog):
    """
    The whole point of the module. Requiring STEPPER_DEBUG to see these means
    you only find them once you already suspect them.
    """
    caplog.set_level(logging.INFO, logger="stepper.swallowed")

    log_swallowed("BookDetailPage._step_dropdown_shelf", exc)

    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "BookDetailPage._step_dropdown_shelf" in record.getMessage()
    assert type(exc).__name__ in record.getMessage()
    assert "code defect" in record.getMessage()


def test_the_warning_names_the_env_var_that_gives_more(caplog):
    caplog.set_level(logging.INFO, logger="stepper.swallowed")

    log_swallowed("somewhere", AttributeError("boom"))

    assert "STEPPER_DEBUG=1" in caplog.records[-1].getMessage()


# ── STEPPER_DEBUG surfaces everything ─────────────────────────────────────────

def test_the_env_var_promotes_an_ordinary_exception_to_warning(monkeypatch, caplog):
    monkeypatch.setenv("STEPPER_DEBUG", "1")
    caplog.set_level(logging.INFO, logger="stepper.swallowed")

    log_swallowed("SomeResolver.collect", TimeoutError("nope"))

    assert caplog.records[-1].levelno == logging.WARNING


def test_the_env_var_adds_a_traceback(monkeypatch, caplog):
    monkeypatch.setenv("STEPPER_DEBUG", "1")
    caplog.set_level(logging.INFO, logger="stepper.swallowed")

    try:
        raise ValueError("with a real traceback")
    except ValueError as exc:
        log_swallowed("somewhere", exc)

    assert "Traceback" in caplog.records[-1].getMessage()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "y", "on", " on "])
def test_truthy_env_values(value, monkeypatch):
    monkeypatch.setenv("STEPPER_DEBUG", value)
    assert debug_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_falsy_env_values(value, monkeypatch):
    monkeypatch.setenv("STEPPER_DEBUG", value)
    assert debug_enabled() is False


def test_the_env_is_read_per_call_not_cached_at_import(monkeypatch):
    """A cached module-level constant would make this untestable and unsettable."""
    monkeypatch.delenv("STEPPER_DEBUG", raising=False)
    assert debug_enabled() is False

    monkeypatch.setenv("STEPPER_DEBUG", "1")
    assert debug_enabled() is True


# ── Caller's logger ───────────────────────────────────────────────────────────

def test_a_caller_can_log_through_its_own_logger(caplog):
    caplog.set_level(logging.DEBUG, logger="my.module")
    mine = logging.getLogger("my.module")

    log_swallowed("MyThing.method", TimeoutError("nope"), mine)

    assert [r.name for r in caplog.records] == ["my.module"]


def test_the_default_logger_is_greppable():
    """One logger name for every swallow, so they can be filtered as a group."""
    import poms.shared.diagnostics as diagnostics

    assert diagnostics._logger.name == "stepper.swallowed"


# ── It must never break its caller ────────────────────────────────────────────

def test_a_broken_logger_does_not_raise():
    """A diagnostic that can break the code it diagnoses is worse than none."""
    broken = logging.getLogger("broken")
    broken.warning = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("logging is down"))
    broken.debug = broken.warning

    log_swallowed("somewhere", AttributeError("boom"), broken)   # must not raise


def test_an_exception_with_a_broken_repr_does_not_raise():
    class Nasty(AttributeError):
        def __str__(self):
            raise RuntimeError("cannot render me")

    log_swallowed("somewhere", Nasty())        # must not raise


def test_it_returns_none_so_it_cannot_be_mistaken_for_a_result():
    assert log_swallowed("somewhere", ValueError("x")) is None
