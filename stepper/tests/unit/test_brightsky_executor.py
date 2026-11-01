"""
Tests for stepper/brightsky/executor.py — the pieces that decide each step's
outcome (ticket 05): RecordingResolver, ExpectationHook, ExecutedStep and
executed_steps.

A passed report auto-verifies a BrightSky version, so these pin the gate:
an outcome that does not hold fails the step, a check that raises is "not
met", a page off its expected URL stops the step before it acts, and a healed
step is never reported passed.
"""
from __future__ import annotations

import dataclasses
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.brightsky.executor import (
    ExecutedStep, ExpectationHook, RecordingResolver, StepExecutor, executed_steps,
)
from stepper.brightsky.mapping import MappedWorkflow, StepExpectation
from stepper.engine.interfaces import (
    ActionFactory, ActionStrategy, ResolveResult, StepConfig, StepResult,
)
from stepper.engine.runner.hooks import StepHook
from stepper.engine.runner.step_runner import StepRunner


# ── Doubles ───────────────────────────────────────────────────────────────────

class FakeLocator:
    def __init__(self, count: int = 0, value: str | None = None,
                 raises: Exception | None = None):
        self._count = count
        self._value = value
        self._raises = raises
        self.timeouts: list = []

    async def count(self) -> int:
        if self._raises is not None:
            raise self._raises
        return self._count

    async def input_value(self, *, timeout=None) -> str:
        self.timeouts.append(timeout)
        if self._raises is not None:
            raise self._raises
        if self._value is None:
            raise RuntimeError("Error: Node is not an <input>, <textarea> or <select> element")
        return self._value


class FakePage:
    """A page with a URL and locators keyed by how they were asked for."""

    def __init__(self, url: str = "https://openlibrary.org/",
                 locators: dict | None = None, urls: list[str] | None = None):
        self._url = url
        self._urls = list(urls or [])
        self._locators = locators or {}
        self.calls: list[tuple] = []

    @property
    def url(self) -> str:
        if self._urls:
            self._url = self._urls.pop(0)
        return self._url

    def _get(self, key):
        self.calls.append(key)
        return self._locators.get(key, FakeLocator())

    def get_by_role(self, role, *, name=None, exact=None):
        return self._get(("role", role, name, exact))

    def get_by_text(self, text, *, exact=None):
        return self._get(("text", text, exact))

    def locator(self, selector):
        return self._get(("locator", selector))


def expectation(start_url=None, match_mode=None, kind=None, element=None,
                url_contains=None) -> StepExpectation:
    return StepExpectation(start_url=start_url, match_mode=match_mode,
                           outcome_kind=kind, outcome_element=element,
                           url_contains=url_contains)


def step(description="Search for 'The Hobbit'", action="fill", **kwargs) -> StepConfig:
    return StepConfig(action=action, description=description, **kwargs)


def hook_for(exp: StepExpectation, description="Search for 'The Hobbit'") -> ExpectationHook:
    return ExpectationHook({description: exp}, timeout_s=0.05, poll_s=0.01)


# ── ExpectationHook.after: url_change ─────────────────────────────────────────

async def test_url_change_met_keeps_the_step_passed():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(urls=["https://openlibrary.org/",
                          "https://openlibrary.org/search?q=the+hobbit"])

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "passed"
    assert result.error == ""


async def test_url_change_not_met_fails_the_step():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(url="https://openlibrary.org/")

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error.startswith("expected outcome not met: ")
    assert "/search" in result.error


async def test_url_change_is_polled_until_it_holds():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(urls=["https://openlibrary.org/", "https://openlibrary.org/",
                          "https://openlibrary.org/", "https://openlibrary.org/search?q=x"])

    hook = ExpectationHook({cfg.description: expectation(kind="url_change",
                                                         url_contains="/search")},
                           timeout_s=1.0, poll_s=0.01)
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "passed"


async def test_a_healed_step_whose_outcome_is_not_met_is_failed():
    cfg = step()
    result = StepResult(step=cfg, status="healed", healed_element={"tier": "cheap"})
    page = FakePage(url="https://openlibrary.org/")

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error.startswith("expected outcome not met: ")


async def test_a_bare_url_change_with_an_unchanged_url_is_not_met():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(url="https://openlibrary.org/")

    hook = hook_for(expectation(kind="url_change"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error == "expected outcome not met: URL changes"


async def test_a_bare_url_change_with_a_changed_url_is_met():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(urls=["https://openlibrary.org/", "https://openlibrary.org/books"])

    hook = hook_for(expectation(kind="url_change"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "passed"


async def test_url_contains_already_on_the_unchanged_page_is_not_met():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(url="https://openlibrary.org/search?q=x")

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    await hook.before(page, cfg, 1)
    await hook.after(page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error == "expected outcome not met: URL changes to contain '/search'"


async def test_a_url_change_whose_before_url_was_never_read_is_not_met():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(url="https://openlibrary.org/search?q=x")

    await hook_for(expectation(kind="url_change", url_contains="/search")).after(
        page, cfg, result, 1)

    assert result.status == "failed"


async def test_a_url_change_whose_before_url_raises_is_not_met():
    class NoUrlYet(FakePage):
        reads = 0

        @property
        def url(self) -> str:
            NoUrlYet.reads += 1
            if NoUrlYet.reads == 1:
                raise RuntimeError("page closed")
            return "https://openlibrary.org/search?q=x"

    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = NoUrlYet()

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    assert await hook.before(page, cfg, 1) is None
    await hook.after(page, cfg, result, 1)

    assert result.status == "failed"


async def test_a_heal_replacements_before_keeps_the_url_from_before_the_step():
    # The outer runner's before reads "/", a replacement runner's before for the
    # same description reads the moved page; the check compares with "/".
    cfg = step()
    replaced = StepResult(step=cfg, status="healed")
    page = FakePage(urls=["https://openlibrary.org/", "https://openlibrary.org/search?q=x",
                          "https://openlibrary.org/search?q=x"])

    hook = hook_for(expectation(kind="url_change", url_contains="/search"))
    await hook.before(page, cfg, 1)
    await hook.before(page, cfg, 0)
    await hook.after(page, cfg, replaced, 1)

    assert replaced.status == "healed"


async def test_a_failed_step_is_not_checked_and_keeps_its_error():
    cfg = step()
    result = StepResult(step=cfg, status="failed", error="Element not found")
    page = MagicMock()

    await hook_for(expectation(kind="url_change", url_contains="/search")).after(
        page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error == "Element not found"


async def test_a_step_with_no_expectation_is_left_alone():
    cfg = step(description="not mapped")
    result = StepResult(step=cfg, status="passed")

    await hook_for(expectation(kind="url_change", url_contains="/search")).after(
        FakePage(url="https://openlibrary.org/"), cfg, result, 1)

    assert result.status == "passed"


async def test_a_step_with_no_outcome_is_left_alone():
    cfg = step()
    result = StepResult(step=cfg, status="passed")

    await hook_for(expectation()).after(FakePage(), cfg, result, 1)

    assert result.status == "passed"


# ── ExpectationHook.after: element outcomes ───────────────────────────────────

async def test_value_set_whose_input_value_raises_is_not_met():
    cfg = step(input_value="The Hobbit")
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={
        ("locator", '[placeholder="Search"]'): FakeLocator(raises=RuntimeError("detached")),
    })

    await hook_for(expectation(kind="value_set",
                               element={"css": '[placeholder="Search"]'})).after(
        page, cfg, result, 1)

    assert result.status == "failed"
    assert result.error.startswith("expected outcome not met: ")


async def test_value_set_on_a_non_input_is_not_met():
    cfg = step(input_value="The Hobbit")
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={("locator", "#title"): FakeLocator(count=1, value=None)})

    await hook_for(expectation(kind="value_set", element={"id": "title"})).after(
        page, cfg, result, 1)

    assert result.status == "failed"


async def test_value_set_equal_to_the_steps_input_value_is_met():
    cfg = step(input_value="The Hobbit")
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={
        ("locator", '[placeholder="Search"]'): FakeLocator(count=1, value="The Hobbit"),
    })

    await hook_for(expectation(kind="value_set",
                               element={"css": '[placeholder="Search"]'})).after(
        page, cfg, result, 1)

    assert result.status == "passed"


async def test_value_set_with_another_value_is_not_met():
    cfg = step(input_value="The Hobbit")
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={
        ("locator", '[placeholder="Search"]'): FakeLocator(count=1, value="Dune"),
    })

    await hook_for(expectation(kind="value_set",
                               element={"css": '[placeholder="Search"]'})).after(
        page, cfg, result, 1)

    assert result.status == "failed"


async def test_element_appears_met_and_not_met():
    cfg = step()
    element = {"role": "link", "name": "The Hobbit"}
    met = StepResult(step=cfg, status="passed")
    unmet = StepResult(step=cfg, status="passed")
    present = FakePage(locators={("role", "link", "The Hobbit", True): FakeLocator(count=2)})

    hook = hook_for(expectation(kind="element_appears", element=element))
    await hook.after(present, cfg, met, 1)
    await hook.after(FakePage(), cfg, unmet, 1)

    assert met.status == "passed"
    assert unmet.status == "failed"
    assert unmet.error.startswith("expected outcome not met: ")


async def test_element_gone_met_and_not_met():
    cfg = step()
    element = {"text": "Loading"}
    met = StepResult(step=cfg, status="passed")
    unmet = StepResult(step=cfg, status="passed")
    still_there = FakePage(locators={("text", "Loading", True): FakeLocator(count=1)})

    hook = hook_for(expectation(kind="element_gone", element=element))
    await hook.after(FakePage(), cfg, met, 1)
    await hook.after(still_there, cfg, unmet, 1)

    assert met.status == "passed"
    assert unmet.status == "failed"


async def test_a_count_that_raises_is_not_met_not_a_pass():
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={("locator", ".gone"): FakeLocator(raises=RuntimeError("boom"))})

    await hook_for(expectation(kind="element_gone", element={"css": ".gone"})).after(
        page, cfg, result, 1)

    assert result.status == "failed"


async def test_value_set_bounds_input_value_by_the_time_left():
    cfg = step(input_value="The Hobbit")
    result = StepResult(step=cfg, status="passed")
    field = FakeLocator(count=1, value="The Hobbit")
    page = FakePage(locators={("locator", "#q"): field})

    hook = ExpectationHook({cfg.description: expectation(kind="value_set",
                                                         element={"id": "q"})},
                           timeout_s=2.0, poll_s=0.01)
    await hook.after(page, cfg, result, 1)

    assert result.status == "passed"
    assert len(field.timeouts) == 1
    assert 0 < field.timeouts[0] <= 2000


async def test_an_element_cfg_with_no_locator_fields_is_not_met_at_once():
    cfg = step()
    result = StepResult(step=cfg, status="passed")

    hook = ExpectationHook({cfg.description: expectation(kind="element_appears",
                                                         element={"placeholder": "x"})},
                           timeout_s=5.0, poll_s=0.01)
    started = time.monotonic()
    await hook.after(FakePage(), cfg, result, 1)

    assert result.status == "failed"
    assert time.monotonic() - started < 1.0


async def test_an_unknown_outcome_kind_is_not_met_at_once():
    cfg = step()
    result = StepResult(step=cfg, status="passed")

    hook = ExpectationHook({cfg.description: expectation(kind="title_change",
                                                         element={"css": "h1"})},
                           timeout_s=5.0, poll_s=0.01)
    started = time.monotonic()
    await hook.after(FakePage(), cfg, result, 1)

    assert result.status == "failed"
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("element, key", [
    ({"role": "button", "name": "Go"}, ("role", "button", "Go", True)),
    ({"text": "Go"}, ("text", "Go", True)),
    ({"css": "button.go"}, ("locator", "button.go")),
    ({"xpath": "//button"}, ("locator", "xpath=//button")),
    ({"id": "go"}, ("locator", "#go")),
])
async def test_the_outcome_locator_is_built_from_the_element_cfg(element, key):
    cfg = step()
    result = StepResult(step=cfg, status="passed")
    page = FakePage(locators={key: FakeLocator(count=1)})

    await hook_for(expectation(kind="element_appears", element=element)).after(
        page, cfg, result, 1)

    assert result.status == "passed"
    assert page.calls[0] == key


# ── ExpectationHook.before ────────────────────────────────────────────────────

async def test_before_lets_a_step_on_its_expected_page_run():
    cfg = step()
    hook = hook_for(expectation(start_url="/search"))

    assert await hook.before(FakePage(url="https://openlibrary.org/search?q=x"), cfg, 1) is None


async def test_before_fails_a_step_off_its_expected_page():
    cfg = step()
    hook = hook_for(expectation(start_url="/search"))

    aborted = await hook.before(FakePage(url="https://openlibrary.org/works/OL1W"), cfg, 1)

    assert aborted is not None
    assert aborted.status == "failed"
    assert aborted.error == ("not on the expected page: /works/OL1W does not match "
                             "/search (startsWith)")


async def test_before_uses_the_steps_match_mode():
    cfg = step()
    hook = hook_for(expectation(start_url="works", match_mode="includes"))

    assert await hook.before(FakePage(url="https://openlibrary.org/works/OL1W"), cfg, 1) is None
    aborted = await hook.before(FakePage(url="https://openlibrary.org/search"), cfg, 1)
    assert aborted.error == "not on the expected page: /search does not match works (includes)"


async def test_before_without_a_start_url_does_nothing():
    cfg = step()

    assert await hook_for(expectation(kind="url_change")).before(MagicMock(), cfg, 1) is None


class CountingAction(ActionStrategy):
    action_name = "scripted"
    domain = "web"

    def __init__(self):
        self.calls = 0

    async def _execute(self, page, step, resolver, context, behaviour=None):
        self.calls += 1
        return StepResult(step=step, status="passed")


class OneActionFactory(ActionFactory):
    def __init__(self, action):
        self._action = action

    def create(self, action_name):
        return self._action


def _runner(page, action) -> StepRunner:
    behaviour = MagicMock()
    behaviour.inter_step_delay = AsyncMock(return_value=None)
    return StepRunner(page=page, action_factory=OneActionFactory(action),
                      reporter=MagicMock(), behaviour=behaviour)


async def test_a_start_url_mismatch_fails_the_step_before_the_action_runs():
    action = CountingAction()
    cfg = step(action="scripted")
    runner = _runner(FakePage(url="https://openlibrary.org/elsewhere"), action)
    runner.add_hook("web", hook_for(expectation(start_url="/search"), cfg.description))

    results, _ = await runner.run([cfg])

    assert action.calls == 0
    assert results[0].status == "failed"
    assert results[0].error.startswith("not on the expected page: /elsewhere")


async def test_an_unmet_outcome_fails_the_step_in_a_real_run():
    action = CountingAction()
    cfg = step(action="scripted")
    runner = _runner(FakePage(url="https://openlibrary.org/"), action)
    runner.add_hook("web", hook_for(expectation(kind="url_change", url_contains="/search"),
                                    cfg.description))

    results, _ = await runner.run([cfg])

    assert action.calls == 1
    assert results[0].status == "failed"
    assert results[0].error.startswith("expected outcome not met: ")


# ── RecordingResolver ─────────────────────────────────────────────────────────

def _inner(*results: ResolveResult) -> MagicMock:
    inner = MagicMock()
    inner.resolve = AsyncMock(side_effect=list(results))
    return inner


async def test_recording_resolver_keeps_the_first_method_for_a_description():
    inner = _inner(ResolveResult(found=True, method="role"),
                   ResolveResult(found=True, method="css"))
    resolver = RecordingResolver(inner)

    resolver.set_context_description("d")
    await resolver.resolve(MagicMock(), {"role": "button"}, "d")
    await resolver.resolve(MagicMock(), {"css": ".x"}, "d")

    assert resolver.tiers == {"d": "role"}


async def test_a_first_miss_is_recorded_as_none_and_not_overwritten():
    inner = _inner(ResolveResult(found=False, method="not-found"),
                   ResolveResult(found=True, method="css"))
    resolver = RecordingResolver(inner)

    await resolver.resolve(MagicMock(), {"css": ".x"}, "d")
    second = await resolver.resolve(MagicMock(), {"css": ".y"}, "d")

    assert second.found is True
    assert resolver.tiers == {"d": None}


async def test_each_description_gets_its_own_first_method():
    inner = _inner(ResolveResult(found=True, method="role"),
                   ResolveResult(found=True, method="text"))
    resolver = RecordingResolver(inner)

    await resolver.resolve(MagicMock(), {}, "one")
    await resolver.resolve(MagicMock(), {}, "two")

    assert resolver.tiers == {"one": "role", "two": "text"}


async def test_a_resolve_without_a_description_uses_the_context_description():
    inner = _inner(ResolveResult(found=True, method="role"))
    resolver = RecordingResolver(inner)

    resolver.set_context_description("from the runner")
    await resolver.resolve(MagicMock(), {})

    inner.set_context_description.assert_called_once_with("from the runner")
    assert resolver.tiers == {"from the runner": "role"}


@pytest.mark.parametrize("strict", [True, False])
async def test_recording_resolver_passes_strict_through_unchanged(strict):
    inner = _inner(ResolveResult(found=False))
    resolver = RecordingResolver(inner)
    page, cfg = MagicMock(), {"css": ".x"}

    await resolver.resolve(page, cfg, "desc", strict=strict, action="click")

    assert inner.resolve.await_args.args == (page, cfg, "desc")
    assert inner.resolve.await_args.kwargs == {"strict": strict, "action": "click"}


async def test_recording_resolver_returns_the_inner_result_unchanged():
    expected = ResolveResult(found=True, locator=object(), confidence=0.9, method="role")
    resolver = RecordingResolver(_inner(expected))

    assert await resolver.resolve(MagicMock(), {}, "d") is expected


class ResolvingAction(ActionStrategy):
    """Resolves the step's element once, as ClickAction and FillAction do."""
    action_name = "scripted"
    domain = "web"

    async def _execute(self, page, step, resolver, context, behaviour=None):
        found = await resolver.resolve(page, step.element, step.description, strict=True)
        status = "passed" if found.found else "failed"
        return StepResult(step=step, status=status)


async def test_a_passed_mapped_step_always_has_its_first_resolves_tier():
    # Mapped steps keep StepConfig's retry=0, so the first resolve is the one
    # the step acts on: a miss fails it, and a later find cannot make it pass
    # with no tier.
    inner = _inner(ResolveResult(found=False, method="not-found"),
                   ResolveResult(found=True, method="css"))
    recording = RecordingResolver(inner)
    cfg = step(description=ONE, action="scripted", element={"css": ".x"})
    assert cfg.retry == 0
    behaviour = MagicMock()
    behaviour.inter_step_delay = AsyncMock(return_value=None)
    runner = StepRunner(page=FakePage(), action_factory=OneActionFactory(ResolvingAction()),
                        resolver=recording, reporter=MagicMock(), behaviour=behaviour)

    results, _ = await runner.run([cfg])
    out = executed_steps(MappedWorkflow(steps=[cfg], step_numbers={ONE: 1}, expectations={}),
                         results, recording.tiers)

    assert inner.resolve.await_count == 1
    assert out == [ExecutedStep(1, "failed", False, None, False, None, results[0].error)]


def test_other_attributes_are_delegated_to_the_inner_resolver():
    inner = MagicMock()
    inner.some_setting = 42
    resolver = RecordingResolver(inner)

    assert resolver.some_setting == 42


# ── ExecutedStep / executed_steps ─────────────────────────────────────────────

NAV, ONE, TWO, THREE = "Step 1: open https://openlibrary.org/", "a", "b", "c"


def mapped() -> MappedWorkflow:
    steps = [StepConfig(action="navigate", description=NAV, url="https://openlibrary.org/"),
             step(ONE), step(TWO, action="click"), step(THREE, action="click")]
    return MappedWorkflow(steps=steps,
                          step_numbers={NAV: 1, ONE: 1, TWO: 2, THREE: 3},
                          expectations={})


def result(description, status, **kwargs) -> StepResult:
    return StepResult(step=step(description), status=status, **kwargs)


def test_all_passed():
    results = [result(NAV, "passed"), result(ONE, "passed"), result(TWO, "passed"),
               result(THREE, "passed")]

    out = executed_steps(mapped(), results, {ONE: "role", TWO: "css", THREE: "text"})

    assert out == [
        ExecutedStep(1, "passed", True, "role", False, None, ""),
        ExecutedStep(2, "passed", True, "css", False, None, ""),
        ExecutedStep(3, "passed", True, "text", False, None, ""),
    ]


def test_a_healed_step_is_failed_with_its_tier_and_healed_element():
    healed_element = {"original": {"role": "link", "name": "x"},
                      "healed": {"css": "a.x"}, "tier": "cheap"}
    results = [result(NAV, "passed"), result(ONE, "passed"),
               result(TWO, "healed", healed_element=healed_element),
               result(THREE, "passed")]

    out = executed_steps(mapped(), results, {ONE: "role", TWO: None, THREE: "text"})

    assert out[1] == ExecutedStep(2, "failed", False, "cheap", True, healed_element, "")
    assert out[0].outcome == out[2].outcome == "passed"


def test_a_healed_step_without_healed_element_is_tier_healer():
    results = [result(NAV, "passed"), result(ONE, "passed"), result(TWO, "healed"),
               result(THREE, "passed")]

    out = executed_steps(mapped(), results, {ONE: "role", TWO: None, THREE: "text"})

    assert out[1] == ExecutedStep(2, "failed", False, "healer", True, None, "")


def test_a_healed_element_without_a_tier_is_tier_healer():
    healed_element = {"original": {}, "healed": {"css": "a"}}
    results = [result(NAV, "passed"), result(ONE, "passed"),
               result(TWO, "healed", healed_element=healed_element)]

    out = executed_steps(mapped(), results, {ONE: "role"})

    assert out[1].tier == "healer"
    assert out[1].healed_element == healed_element


def test_a_failed_step_that_never_matched():
    results = [result(NAV, "passed"), result(ONE, "passed"),
               result(TWO, "failed", error="Element not found → not-found")]

    out = executed_steps(mapped(), results, {ONE: "role", TWO: None})

    assert out[1] == ExecutedStep(2, "failed", False, None, False, None,
                                  "Element not found → not-found")
    assert out[2] == ExecutedStep(3, "unchecked", False, None, False, None, "")


def test_an_outcome_failed_step_is_matched():
    results = [result(NAV, "passed"),
               result(ONE, "failed", error="expected outcome not met: URL contains '/search'")]

    out = executed_steps(mapped(), results, {ONE: "css"})

    assert out[0] == ExecutedStep(1, "failed", True, "css", False, None,
                                  "expected outcome not met: URL contains '/search'")
    assert [e.outcome for e in out[1:]] == ["unchecked", "unchecked"]


def test_a_failed_navigate_fails_step_1_and_leaves_the_rest_unchecked():
    results = [result(NAV, "failed", error="net::ERR_NAME_NOT_RESOLVED")]

    out = executed_steps(mapped(), results, {})

    assert out == [
        ExecutedStep(1, "failed", False, None, False, None, "net::ERR_NAME_NOT_RESOLVED"),
        ExecutedStep(2, "unchecked", False, None, False, None, ""),
        ExecutedStep(3, "unchecked", False, None, False, None, ""),
    ]


def test_no_results_at_all_is_every_step_unchecked():
    out = executed_steps(mapped(), [], {})

    assert [(e.step_number, e.outcome, e.matched, e.tier) for e in out] == [
        (1, "unchecked", False, None), (2, "unchecked", False, None),
        (3, "unchecked", False, None)]


def test_the_last_result_for_a_step_number_wins():
    # The navigate passed but step 1's own fill failed: step 1 is failed.
    results = [result(NAV, "passed"), result(ONE, "failed", error="boom")]

    out = executed_steps(mapped(), results, {ONE: None})

    assert out[0].outcome == "failed"
    assert out[0].error == "boom"


def test_a_result_for_an_unmapped_description_is_ignored():
    results = [result(NAV, "passed"), result("scroll_to: a", "passed"),
               result(ONE, "passed")]

    out = executed_steps(mapped(), results, {ONE: "role"})

    assert len(out) == 3
    assert out[0].outcome == "passed"


def test_executed_step_is_frozen():
    executed = ExecutedStep(1, "passed", True, "role", False, None, "")

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(executed, "outcome", "failed")


def test_a_class_with_execute_is_a_step_executor():
    class Stub:
        async def execute(self, mapped, *, headless):
            return []

    assert isinstance(Stub(), StepExecutor)


def test_expectation_hook_is_a_step_hook():
    assert isinstance(ExpectationHook({}), StepHook)
