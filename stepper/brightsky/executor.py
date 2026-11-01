"""
brightsky/executor.py — What decides each BrightSky step's outcome.

A passed report auto-verifies a version, so "passed" is decided here:

- `RecordingResolver` wraps the run's resolver and remembers, per step
  description, the method the *first* resolve found the stored target by (or
  None when it missed). Retries and heal replacements do not overwrite it, so
  a tier describes the stored target, not the heal.
- `ExpectationHook` is the per-step gate, attached with `StepRunner.add_hook`.
  Before a step acts, the page must be on the step's expected URL; after it
  passed (or healed), its expected outcome must hold within a timeout. A check
  that raises counts as not met. A `url_change` needs the URL to differ from
  the one `before` read, as bright-sky's own outcome check does.
- `executed_steps` turns StepRunner's results into one `ExecutedStep` per
  BrightSky step. A healed step is `failed`: a version only verifies when its
  stored steps work as stored.

The executors that build a runner around these pieces are ticket 13.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from stepper.brightsky.mapping import MappedWorkflow, StepExpectation, url_matches
from stepper.engine.interfaces import ResolveResult, StepConfig, StepResult
from stepper.engine.runner.hooks import StepHook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutedStep:
    """One BrightSky step after a run. A healed step's `outcome` is `failed`."""
    step_number: int
    outcome: str                 # passed | failed | unchecked
    matched: bool
    tier: str | None
    healed: bool = False
    healed_element: dict | None = None
    error: str = ""


@runtime_checkable
class StepExecutor(Protocol):
    async def execute(self, mapped: MappedWorkflow, *,
                      headless: bool) -> list[ExecutedStep]:
        """Run the mapped steps; one ExecutedStep per BrightSky step, in order."""
        ...


# ── Which tier found each stored target ───────────────────────────────────────

class RecordingResolver:
    """
    Proxy around a resolver that records the first resolve per description.

    `tiers[description]` is the winning `method` of that description's first
    resolve, or None when it found nothing.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._description = ""
        self.tiers: dict[str, str | None] = {}

    def set_context_description(self, description: str) -> None:
        self._description = description or ""
        self._inner.set_context_description(description)

    async def resolve(self, page, cfg: dict, step_description: str = "",
                      *, strict: bool = False, action: str | None = None) -> ResolveResult:
        result = await self._inner.resolve(page, cfg, step_description,
                                           strict=strict, action=action)
        key = step_description or self._description
        if key not in self.tiers:
            self.tiers[key] = result.method if result.found else None
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ── The per-step gate ─────────────────────────────────────────────────────────

class ExpectationHook(StepHook):
    """
    Checks each mapped step's `StepExpectation`, keyed by step description.

    `before` fails a step whose page is not on its expected URL, so it never
    acts. `after` fails a passed or healed step whose outcome does not hold
    within `timeout_s`, polled every `poll_s`.

    For a `url_change`, `before` records the page URL per description. A heal
    replacement runner calls `before` again for the same description; the
    first URL is kept, so the check compares with the page before the step
    first acted. One hook serves one run.
    """

    def __init__(self, expectations: dict[str, StepExpectation],
                 timeout_s: float = 10.0, poll_s: float = 0.25) -> None:
        self._expectations = expectations
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._urls_before: dict[str, str] = {}

    async def before(self, session, step: StepConfig, idx: int) -> StepResult | None:
        exp = self._expectations.get(step.description)
        if exp is None:
            return None
        if exp.outcome_kind == "url_change" and step.description not in self._urls_before:
            try:
                self._urls_before[step.description] = session.url
            except Exception as exc:
                # Nothing recorded, so `after` counts the outcome as not met.
                logger.warning("[ExpectationHook] step %d: cannot read the URL "
                               "before the step: %s", idx + 1, exc)
        if exp.start_url is None:
            return None
        mode = exp.match_mode or "startsWith"
        try:
            path = urlparse(session.url).path
        except Exception as exc:
            # The runner ignores a hook that raises and runs the step, so a
            # gate must turn its own failure into a failed step.
            logger.warning("[ExpectationHook] step %d: cannot read the page URL: %s",
                           idx + 1, exc)
            return StepResult(step=step, status="failed",
                              error=f"not on the expected page: cannot read the page URL ({exc})")
        if url_matches(path, exp.start_url, exp.match_mode):
            return None
        return StepResult(
            step=step, status="failed",
            error=f"not on the expected page: {path} does not match {exp.start_url} ({mode})",
        )

    async def after(self, session, step: StepConfig, result: StepResult, idx: int) -> None:
        if result.status not in ("passed", "healed"):
            return
        exp = self._expectations.get(step.description)
        if exp is None or exp.outcome_kind is None:
            return
        if await self._holds(session, step, exp, idx):
            return
        result.status = "failed"
        result.error = f"expected outcome not met: {_describe(step, exp)}"

    async def _holds(self, session, step: StepConfig, exp: StepExpectation, idx: int) -> bool:
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                if await self._check(session, step, exp, deadline):
                    return True
            except ValueError as exc:
                # A check that cannot be made (no locator fields, an unknown
                # kind, no URL from before the step) never starts to hold.
                logger.warning("[ExpectationHook] step %d: %s check cannot be made, "
                               "not met: %s", idx + 1, exp.outcome_kind, exc)
                return False
            except Exception as exc:
                logger.warning("[ExpectationHook] step %d: %s check raised, not met: %s",
                               idx + 1, exp.outcome_kind, exc)
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self._poll_s)

    async def _check(self, session, step: StepConfig, exp: StepExpectation,
                     deadline: float) -> bool:
        kind = exp.outcome_kind
        if kind == "url_change":
            before = self._urls_before.get(step.description)
            if before is None:
                raise ValueError("the URL before the step was not recorded")
            url = session.url
            return url != before and (exp.url_contains is None or exp.url_contains in url)
        if kind not in ("element_appears", "element_gone", "value_set"):
            raise ValueError(f"unknown outcome kind {kind!r}")
        locator = _locator(session, exp.outcome_element or {})
        if kind == "element_appears":
            return await locator.count() > 0
        if kind == "element_gone":
            return await locator.count() == 0
        # Playwright's timeout is in ms, and 0 means none: keep it at least 1.
        left_ms = max(1.0, (deadline - time.monotonic()) * 1000)
        return await locator.input_value(timeout=left_ms) == step.input_value


def _locator(session, element: dict):
    if element.get("role") and element.get("name"):
        return session.get_by_role(element["role"], name=element["name"], exact=True)
    if element.get("text"):
        return session.get_by_text(element["text"], exact=True)
    if element.get("css"):
        return session.locator(element["css"])
    if element.get("xpath"):
        return session.locator("xpath=" + element["xpath"])
    if element.get("id"):
        return session.locator("#" + element["id"])
    raise ValueError("outcome element has no role+name, text, css, xpath or id")


def _describe(step: StepConfig, exp: StepExpectation) -> str:
    kind = exp.outcome_kind
    if kind == "url_change":
        if exp.url_contains is None:
            return "URL changes"
        return f"URL changes to contain {exp.url_contains!r}"
    element = exp.outcome_element
    if kind == "element_appears":
        return f"element {element} appears"
    if kind == "element_gone":
        return f"element {element} is gone"
    return f"element {element} has value {step.input_value!r}"


# ── StepRunner results → BrightSky step outcomes ──────────────────────────────

def executed_steps(mapped: MappedWorkflow, results: list[StepResult],
                   tiers: dict[str, str | None]) -> list[ExecutedStep]:
    """
    One ExecutedStep per BrightSky step number, 1 to n, from the *last* result
    whose description maps to it (the navigate and the first acting step are
    both step 1).
    """
    last: dict[int, StepResult] = {}
    for result in results:
        number = mapped.step_numbers.get(result.step.description)
        if number is not None:
            last[number] = result

    count = max(mapped.step_numbers.values(), default=0)
    out: list[ExecutedStep] = []
    for number in range(1, count + 1):
        result = last.get(number)
        if result is None:
            out.append(ExecutedStep(number, "unchecked", False, None))
            continue
        method = tiers.get(result.step.description)
        if result.status == "passed":
            out.append(ExecutedStep(number, "passed", True, method))
        elif result.status == "healed":
            out.append(ExecutedStep(
                number, "failed", False,
                (result.healed_element or {}).get("tier", "healer"),
                healed=True, healed_element=result.healed_element, error=result.error,
            ))
        else:
            out.append(ExecutedStep(number, "failed", method is not None, method,
                                    error=result.error))
    return out
