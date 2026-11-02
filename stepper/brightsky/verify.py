"""
brightsky/verify.py — Verify a BrightSky workflow end to end.

`verify_slug` checks the token, fetches the workflow, maps its current
version, runs it, reports the run, and, when every step passed or healed,
proposes the healed steps as a new unverified version. `verify_all_unverified`
does that for each entry of the verification queue, in the backend's order.

What the store hears is decided here. A `passed` report auto-promotes a
version, so a run is reported `passed` only when every step passed as stored;
a healed step is `failed` in the report (spec.md, "Healed means failed").

A 401 or 403 from any call is never an outcome: the token is bad for every
later call too, so it propagates for the CLI to exit 3.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field

from stepper.brightsky.client import BrightSkyClient, BrightSkyHttpError
from stepper.brightsky.config import BrightSkyConfig
from stepper.brightsky.executor import ExecutedStep, PipelineExecutor, StepExecutor
from stepper.brightsky.mapping import UnmappableStep, map_version
from stepper.brightsky.models import (
    BrightSkyResponseError,
    Proposal,
    RunReport,
    RunStep,
    WorkflowDetail,
    new_idempotency_key,
)
from stepper.brightsky.targets import target_from_element

__all__ = [
    "QueueRun", "VerifyOutcome", "make_client", "make_executor",
    "verify_all_unverified", "verify_slug",
]

logger = logging.getLogger(__name__)

#: The statuses that mean the token was refused; never turned into an outcome.
TOKEN_REJECTED = frozenset({401, 403})
#: Healed tiers that used no AI, so the proposal's source is `stepper`.
FREE_HEAL_TIERS = frozenset({"embed_direct", "heal_cache"})
UNMAPPED_TIER = "unmapped"


@dataclass(frozen=True)
class VerifyOutcome:
    """What one workflow's verification came to."""
    slug: str
    #: The version run (or asked for, when skipped); None for a rejected queue entry.
    version: int | None
    status: str                  # passed | failed | healed | skipped
    reason: str = ""
    proposed_version: int | None = None


@dataclass(frozen=True)
class QueueRun:
    """One outcome per queue entry, in queue order (rejected entries first)."""
    outcomes: list[VerifyOutcome] = field(default_factory=list)


def make_executor() -> StepExecutor:
    """The real executor; the CLI calls this and tests monkeypatch it."""
    return PipelineExecutor()


def make_client(config: BrightSkyConfig) -> BrightSkyClient:
    """The real client; the CLI calls this and tests monkeypatch it."""
    return BrightSkyClient(config)


def _reraise_if_token_rejected(err: BrightSkyHttpError) -> None:
    if err.status in TOKEN_REJECTED:
        raise err


async def verify_slug(client: BrightSkyClient, executor: StepExecutor, slug: str, *,
                      version: int | None = None, headless: bool = True,
                      check_token: bool = True) -> VerifyOutcome:
    """Verify `slug`'s current version. Raises BrightSkyHttpError for a 401/403,
    and lets the token check's and the fetch's errors propagate."""
    if check_token:
        # The fetch is public, so this guarded call is what finds a bad token
        # before a browser starts. Its body is not used.
        client.queue()
    detail = client.get_workflow(slug)
    current = detail.current_version
    if version is not None and version != current:
        logger.info("brightsky verify skipped slug=%s version=%s current=%s",
                    slug, version, current)
        return VerifyOutcome(slug, version, "skipped",
                             reason=f"not the current version (v{current})")

    key = new_idempotency_key()
    try:
        mapped = map_version(detail)
    except UnmappableStep as err:
        return _report_unmappable(client, detail, key, err)

    executed = await executor.execute(mapped, headless=headless)
    all_passed = all(step.outcome == "passed" for step in executed)
    report = RunReport(
        version=current,
        steps=[RunStep(e.step_number, e.matched, e.tier, e.outcome) for e in executed],
        result="passed" if all_passed else "failed",
        idempotency_key=key,
    )
    try:
        client.report_run(slug, report)
    except BrightSkyHttpError as err:
        _reraise_if_token_rejected(err)
        logger.warning("brightsky run report failed slug=%s version=%s key=%s error=%s",
                       slug, current, key, err)
        return VerifyOutcome(slug, current, "failed", reason=f"report failed: {err}")
    logger.info("brightsky run reported slug=%s version=%s key=%s result=%s",
                slug, current, key, report.result)

    if all_passed:
        return VerifyOutcome(slug, current, "passed")

    healed = [e for e in executed if e.healed]
    if not healed or not all(e.outcome == "passed" or e.healed for e in executed):
        # Nothing healed, or a heal that another failing step makes moot.
        return VerifyOutcome(slug, current, "failed", reason=_first_error(executed))

    proposal, why_not = _proposal(detail, key, healed)
    if proposal is None:
        logger.info("brightsky proposal not made slug=%s version=%s reason=%s",
                    slug, current, why_not)
        return VerifyOutcome(slug, current, "healed", reason=why_not)
    try:
        proposed = client.propose_version(slug, proposal)
    except BrightSkyHttpError as err:
        _reraise_if_token_rejected(err)
        logger.warning("brightsky proposal failed slug=%s version=%s key=%s error=%s",
                       slug, current, key, err)
        return VerifyOutcome(slug, current, "healed", reason=f"proposal failed: {err}")
    logger.info("brightsky proposal made slug=%s version=%s key=%s proposed=%s source=%s",
                slug, current, key, proposed, proposal.source)
    return VerifyOutcome(slug, current, "healed", proposed_version=proposed)


async def verify_all_unverified(client: BrightSkyClient, executor: StepExecutor, *,
                                headless: bool = True) -> QueueRun:
    """Verify every queue entry, one at a time, in the backend's order, with no cap.
    A 401/403 stops the walk and propagates; any other request error fails that
    entry only."""
    items, rejected = client.queue()
    outcomes = [VerifyOutcome("?", None, "failed", reason=reason) for reason in rejected]
    for item in items:
        try:
            outcome = await verify_slug(client, executor, item.slug, version=item.version,
                                        headless=headless, check_token=False)
        except BrightSkyHttpError as err:
            _reraise_if_token_rejected(err)
            logger.warning("brightsky queue entry failed slug=%s version=%s error=%s",
                           item.slug, item.version, err)
            outcome = VerifyOutcome(item.slug, item.version, "failed", reason=str(err))
        except BrightSkyResponseError as err:
            logger.warning("brightsky queue entry failed slug=%s version=%s error=%s",
                           item.slug, item.version, err)
            outcome = VerifyOutcome(item.slug, item.version, "failed", reason=str(err))
        outcomes.append(outcome)
    return QueueRun(outcomes)


# ── helpers ──────────────────────────────────────────────────────────────────

def _report_unmappable(client: BrightSkyClient, detail: WorkflowDetail, key: str,
                       err: UnmappableStep) -> VerifyOutcome:
    """Post a failed report for a version that cannot run: the bad step `failed`
    (tier `unmapped`), every other step `unchecked`. Nothing is launched."""
    reason = f"step {err.step_number}: {err.reason}"
    steps = [
        RunStep(n, False, UNMAPPED_TIER, "failed") if n == err.step_number
        else RunStep(n, False, None, "unchecked")
        for n in range(1, len(detail.steps) + 1)
    ]
    report = RunReport(version=detail.current_version, steps=steps, result="failed",
                       idempotency_key=key)
    try:
        client.report_run(detail.slug, report)
    except BrightSkyHttpError as report_err:
        _reraise_if_token_rejected(report_err)
        logger.warning("brightsky run report failed slug=%s version=%s key=%s error=%s",
                       detail.slug, detail.current_version, key, report_err)
        reason = f"{reason}; report failed: {report_err}"
    else:
        logger.info("brightsky unmappable version reported slug=%s version=%s key=%s "
                    "step=%s", detail.slug, detail.current_version, key, err.step_number)
    return VerifyOutcome(detail.slug, detail.current_version, "failed", reason=reason)


def _first_error(executed: list[ExecutedStep]) -> str:
    for step in executed:
        if step.outcome == "failed" and not step.healed:
            return f"step {step.step_number}: {step.error}" if step.error \
                else f"step {step.step_number} failed"
    return ""


def _proposal(detail: WorkflowDetail, key: str,
              healed: list[ExecutedStep]) -> tuple[Proposal | None, str]:
    """The fetched steps with each healed step's target replaced, or (None, why)."""
    steps = copy.deepcopy(detail.steps)
    changes: list[str] = []
    for step in healed:
        n = step.step_number
        element = (step.healed_element or {}).get("healed")
        if not element:
            return None, (f"step {n} healed by a scroll or wait, so its element did "
                          "not change: nothing to propose")
        old = steps[n - 1].get("target")
        new = target_from_element(element, original=old)
        if new is None:
            return None, (f"step {n}: the store cannot describe the healed element "
                          f"{_shown(element)}: nothing to propose")
        steps[n - 1]["target"] = new
        changes.append(f"step {n} target {_target_text(old)} -> {_target_text(new)}")

    source = ("stepper" if all(s.tier in FREE_HEAL_TIERS for s in healed) else "haiku")
    note = (f"Healed by stepper run {key} of v{detail.current_version}: "
            + "; ".join(changes))
    return Proposal(steps=steps, source=source, note=note), ""


def _target_text(target: object) -> str:
    """A short, readable form of a BrightSky target for the proposal's note."""
    if not isinstance(target, dict):
        return "(none)"
    parts: list[str] = []
    role = target.get("role")
    if isinstance(role, str) and role:
        parts.append(role)
    name = target.get("accessibleName")
    if isinstance(name, str) and name:
        parts.append(json.dumps(name, ensure_ascii=False))
    selectors = target.get("selectors")
    if isinstance(selectors, list):
        parts.extend(s for s in selectors if isinstance(s, str) and s)
    return " ".join(parts) or "(empty)"


def _shown(element: dict) -> str:
    return json.dumps(element, ensure_ascii=False, sort_keys=True)[:200]
