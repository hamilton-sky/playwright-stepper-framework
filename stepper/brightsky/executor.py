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

- `EngineExecutor` runs a mapped workflow on a real StepRunner over a page it
  is given, launching nothing; `PipelineExecutor` runs it headless through
  `stepper.main`'s pipeline. Both heal in the strict order with no heal cache,
  and both accept only a heal that changes the failed step's element: any
  other replacement (another action, a new URL, extra steps) is rejected, so
  a heal reply cannot take a run off the mapped pages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from stepper.brightsky.mapping import MappedWorkflow, StepExpectation, url_matches
from stepper.engine.actions.factory import build_default_registry
from stepper.engine.healer.ai_healer import AiHealer
from stepper.engine.healer.interfaces import DomPayload, HealerStrategy, HealingError
from stepper.engine.interfaces import ResolveResult, StepConfig, StepResult
from stepper.engine.planner.schema_extractor import ActionSchemaExtractor
from stepper.engine.reporter.reporters import CompositeReporter
from stepper.engine.runner.hooks import StepHook
from stepper.engine.runner.step_runner import StepRunner

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


# ── The executors ─────────────────────────────────────────────────────────────

#: One free embed_direct try, then cheap, cheap, big (ticket 12's strict order).
_MAX_HEAL_ATTEMPTS = 3


class _ElementOnlyHealer(HealerStrategy):
    """
    Wraps a healer so a heal can change the failed step's element and nothing
    else. BrightSky only takes a new target back, and the heal prompt carries
    backend and page text, so a reply of other than one step of the same
    action with an element (navigate elsewhere, read a file, add steps)
    raises HealingError, which the heal loop counts as a failed attempt. The
    step that runs is the failed step with the reply's element swapped in, so
    a reply cannot change its URL, value or extra either.
    """

    def __init__(self, inner: HealerStrategy) -> None:
        self._inner = inner

    def tier_for(self, dom: DomPayload, tried: tuple[str, ...]) -> str:
        return self._inner.tier_for(dom, tried)

    async def heal(self, step: StepConfig, error: str, dom: DomPayload,
                   **kwargs: Any) -> list[StepConfig]:
        reply = await self._inner.heal(step, error, dom, **kwargs)
        if len(reply) != 1:
            raise HealingError(
                f"heal for '{step.description}' must be one step, got {len(reply)}")
        healed = reply[0]
        if healed.action != step.action or not healed.element:
            raise HealingError(
                f"heal for '{step.description}' must be a '{step.action}' with an "
                f"element, got '{healed.action}'")
        return [replace(step, element=dict(healed.element))]


class EngineExecutor:
    """
    Runs mapped steps on a real StepRunner over `page`, launching nothing.

    The real action registry, a real AiHealer over `ai_service` (a real
    AIService when None, which makes no request without keys), the strict
    heal order, no heal cache, and a reporter that writes nothing. `page` and
    `resolver` are whatever the caller gives; a test double is fine.
    """

    def __init__(self, page: Any, resolver: Any, *, ai_service: Any = None,
                 max_heal_attempts: int = _MAX_HEAL_ATTEMPTS) -> None:
        self._page = page
        self._resolver = resolver
        self._ai_service = ai_service
        self._max_heal_attempts = max_heal_attempts

    async def execute(self, mapped: MappedWorkflow, *,
                      headless: bool) -> list[ExecutedStep]:
        # `headless` is unused: nothing is launched here.
        registry = build_default_registry()
        resolver = RecordingResolver(self._resolver)
        runner = StepRunner(
            page=self._page,
            action_factory=registry,
            resolver=resolver,
            reporter=CompositeReporter([]),
            healer=_ElementOnlyHealer(AiHealer(ActionSchemaExtractor.extract(registry),
                                               ai_service=self._ai_service)),
            max_heal_attempts=self._max_heal_attempts,
            cache=None,
            strict_heal_order=True,
        )
        runner.add_hook("web", ExpectationHook(mapped.expectations))
        results, _ = await runner.run(mapped.steps)
        return executed_steps(mapped, results, resolver.tiers)


class PipelineExecutor:
    """
    Runs mapped steps through `stepper.main`'s pipeline, in a real browser.

    The steps are written to a temporary workflow file, removed afterwards.
    A DomainNotReadyError (no browser here) propagates before anything opens.
    """

    async def execute(self, mapped: MappedWorkflow, *,
                      headless: bool) -> list[ExecutedStep]:
        # Imported here so that importing this module launches and loads nothing.
        from stepper import main as pipeline

        with tempfile.TemporaryDirectory(prefix="brightsky-verify-") as tmp:
            workflow_path = Path(tmp) / "workflow.json"
            # The run's site comes from a `sites/<name>` part of this path; a
            # site's settings or saved login must never reach a verify run.
            if pipeline._extract_site(str(workflow_path)) != "shared":
                raise RuntimeError(
                    f"temp dir {tmp} names a site; set TMPDIR outside any sites/ folder")
            workflow_path.write_text(json.dumps({
                "name": "brightsky verify",
                "domain": "web",
                "steps": [asdict(step) for step in mapped.steps],
            }), encoding="utf-8")

            cfg = pipeline.RunConfig(
                workflow_path=str(workflow_path),
                headless=headless,
                max_heal_attempts=_MAX_HEAL_ATTEMPTS,
                use_heal_cache=False,
                strict_heal_order=True,
            )
            resolver = RecordingResolver(
                pipeline.build_resolver(pipeline.build_settings(cfg).use_visual_ai))
            prepared = pipeline.prepare_run(cfg, resolver=resolver)

            # The same order as `stepper.main.run()`: closing the sessions is
            # what shuts the browser, so it happens even when the run raised.
            sessions = pipeline.build_session_set(prepared)
            try:
                built = await pipeline.build_pipeline(prepared, sessions)
                built.runner.add_hook("web", ExpectationHook(mapped.expectations))
                # build_pipeline gives no seam for the healer, so it is wrapped here.
                if built.runner._healer is not None:
                    built.runner._healer = _ElementOnlyHealer(built.runner._healer)
                results = await pipeline.execute_pipeline(built)
            finally:
                await sessions.close_all()

        return executed_steps(mapped, results, resolver.tiers)
