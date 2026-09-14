"""
What counts as a successful heal.

Both bugs here were found by putting sd_heal_test into CI and reading the log
instead of the exit code. The workflow reported `healed: 3, failed: 0` while the
login click it was supposed to fix had never happened.

    ⚕ [HealCache] HIT for 'click' — skipping cascade
    ▶ Step 1: Click the Login button to submit credentials
      Deterministic cascade failed — falling through to zero-selector path
      Visual AI disabled — returning not-found
    Recorded step 6: click → skipped
    Recorded step 7: click → healed      ← skipped, then reported healed

Two independent faults produced that line, and either alone would have hidden
the other:

  1. the success check was `all(r.status != "failed")`, and "skipped" is not
     "failed", so a replacement that resolved nothing counted as a heal
  2. `heal_assert` — the guard written to catch precisely this — ran only on the
     cascade path, never on a cache hit

A green run that proves nothing is worse than a red one, because nobody looks
again.
"""
from __future__ import annotations

import pytest

from stepper.engine.interfaces import StepConfig, StepResult
from stepper.engine.runner.step_runner import _heal_assert_passed, _heal_succeeded


def _r(status: str) -> StepResult:
    return StepResult(step=StepConfig(action="click"), status=status)


# ── What counts as healed ─────────────────────────────────────────────────────

def test_a_replacement_that_passed_is_a_heal():
    assert _heal_succeeded([_r("passed")]) is True


def test_a_replacement_that_itself_healed_is_a_heal():
    """Nested healing is legitimate; the element was reached in the end."""
    assert _heal_succeeded([_r("healed")]) is True


def test_a_skipped_replacement_is_not_a_heal():
    """
    The bug. "skipped" means the resolver still could not find the element, so
    the replacement never ran. Counting it as healed reports success for a step
    that did nothing.
    """
    assert _heal_succeeded([_r("skipped")]) is False


def test_a_failed_replacement_is_not_a_heal():
    assert _heal_succeeded([_r("failed")]) is False


def test_a_warned_replacement_is_not_a_heal():
    """
    A warn is a low-confidence act — the resolver was not sure it had the right
    element. Not a basis for declaring a selector repaired.
    """
    assert _heal_succeeded([_r("warned")]) is False


def test_no_replacements_at_all_is_not_a_heal():
    """
    Nothing ran, so nothing was fixed. `all()` over an empty list is True, which
    is exactly how an empty replacement list used to report success.
    """
    assert _heal_succeeded([]) is False


def test_every_replacement_must_pass_not_merely_the_first():
    """A multi-step heal is only healed if the whole sequence worked."""
    assert _heal_succeeded([_r("passed"), _r("skipped")]) is False
    assert _heal_succeeded([_r("passed"), _r("passed")]) is True


@pytest.mark.parametrize("status", ["skipped", "failed", "warned"])
def test_one_bad_step_anywhere_sinks_the_heal(status):
    assert _heal_succeeded([_r("passed"), _r(status), _r("passed")]) is False


# ── heal_assert applies on both paths ─────────────────────────────────────────

async def test_a_step_without_a_heal_assert_passes_vacuously():
    assert await _heal_assert_passed(object(), StepConfig(action="click")) is True


async def test_a_satisfied_heal_assert_passes():
    class _Page:
        url = "https://www.saucedemo.com/inventory.html"

    step = StepConfig(action="click", heal_assert={"url_contains": "/inventory"})

    assert await _heal_assert_passed(_Page(), step) is True


async def test_an_unsatisfied_heal_assert_fails():
    """
    The exact case sd_heal_test carries. The click never navigated, so the URL
    is still the login page — which is what `{"url_contains": "/inventory"}` is
    there to notice.
    """
    class _Page:
        url = "https://www.saucedemo.com/"

    step = StepConfig(action="click", heal_assert={"url_contains": "/inventory"})

    assert await _heal_assert_passed(_Page(), step) is False


# ── The two together ──────────────────────────────────────────────────────────

async def test_the_ci_false_positive_cannot_recur():
    """
    Replays the shape of the run that started this: a cached cfg whose
    replacement was skipped, on a page that never left the login screen.

    Both guards now say no. Either one alone would have caught it, which is why
    both are here — the cache path had neither.
    """
    class _LoginPage:
        url = "https://www.saucedemo.com/"

    step = StepConfig(
        action="click",
        description="Click the Login button to submit credentials",
        element={"css": ".broken-login-btn"},
        heal_assert={"url_contains": "/inventory"},
    )
    rep_results = [_r("skipped")]

    assert _heal_succeeded(rep_results) is False
    assert await _heal_assert_passed(_LoginPage(), step) is False


# ── The flag that makes the CI step measure something ─────────────────────────

def test_the_heal_cache_is_on_by_default():
    """It is a real optimisation; the flag exists to opt out, not to opt in."""
    from stepper.main import RunConfig

    assert RunConfig(task="x").use_heal_cache is True


def test_no_heal_cache_turns_it_off():
    from stepper.cli import build_parser

    args = build_parser().parse_args(["run", "wf", "--heal", "2", "--no-heal-cache"])

    assert args.no_heal_cache is True
