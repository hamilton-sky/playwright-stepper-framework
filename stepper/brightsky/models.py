"""
brightsky/models.py — The BrightSky wire shapes, read and written.

Readers (`QueueItem.from_json`, `WorkflowDetail.from_json`) take untrusted JSON
from the backend and check it field by field. A bad body raises
`BrightSkyResponseError` naming the field; the message names the field only,
never echoes its value, so nothing from a body reaches a log through it.

Writers (`RunStep`, `RunReport`, `Proposal`) check their own fields against the
backend's DTO limits (`ReportRunDto`, `ProposeVersionDto` in bright-sky's
workflow-store-api.dto.ts) when built, so a body the backend would refuse with
a 400 is a `ValueError` here instead. Nothing in this module does I/O.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

#: The backend's slug rule (`WORKFLOW_API_LIMITS.slugPattern`). Use fullmatch:
#: `$` alone would accept a trailing newline.
SLUG_PATTERN = re.compile(r"^[a-z0-9-]{3,100}$")

MAX_STEPS = 50
MAX_TIER = 100
MAX_IDEMPOTENCY_KEY = 100
MAX_NOTE = 1000

STEP_OUTCOMES = frozenset({"passed", "failed", "unchecked"})
RUN_RESULTS = frozenset({"passed", "failed", "incomplete"})
#: The sources stepper proposes with. `claude` is left out on purpose: it needs
#: one passing run to be promoted where these need two (spec.md, "Proposal source").
PROPOSAL_SOURCES = frozenset({"stepper", "haiku"})


class BrightSkyResponseError(Exception):
    """A backend response is malformed. The message names the bad field."""


# ── reading ──────────────────────────────────────────────────────────────────

def _object(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise BrightSkyResponseError(f"{where} must be an object")
    return value


def _str(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise BrightSkyResponseError(f"{where}{key} must be a string")
    return value


def _int(obj: dict, key: str, where: str, minimum: int) -> int:
    value = obj.get(key)
    # bool is an int subclass; True is not a version number.
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise BrightSkyResponseError(f"{where}{key} must be an integer >= {minimum}")
    return value


def _slug(obj: dict, where: str) -> str:
    value = obj.get("slug")
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise BrightSkyResponseError(f"{where}slug must match {SLUG_PATTERN.pattern}")
    return value


@dataclass(frozen=True)
class QueueItem:
    """One entry of `GET /api/workflows/verification-queue`."""
    slug: str
    version: int
    stepper_runs: int
    created_at: str

    @classmethod
    def from_json(cls, raw: Any) -> QueueItem:
        obj = _object(raw, "queue entry")
        return cls(
            slug=_slug(obj, ""),
            version=_int(obj, "version", "", 1),
            stepper_runs=_int(obj, "stepperRuns", "", 0),
            created_at=_str(obj, "createdAt", ""),
        )


@dataclass(frozen=True)
class WorkflowDetail:
    """`GET /api/workflows/:slug`: the current version and its steps."""
    slug: str
    site: str
    current_version: int
    #: The step dicts exactly as received, so a proposal can copy them unchanged.
    steps: list[dict]
    #: (version number, note) for every version, as the propose retry check reads them.
    versions: list[tuple[int, str | None]]

    @classmethod
    def from_json(cls, raw: Any) -> WorkflowDetail:
        obj = _object(raw, "workflow")
        current = _object(obj.get("currentVersion"), "currentVersion")

        steps = obj.get("currentSteps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise BrightSkyResponseError(
                f"currentSteps must be a list of 1 to {MAX_STEPS} steps")
        for i, step in enumerate(steps):
            _str(_object(step, f"currentSteps[{i}]"), "title", f"currentSteps[{i}].")

        listed = obj.get("versions")
        if not isinstance(listed, list):
            raise BrightSkyResponseError("versions must be a list")
        versions: list[tuple[int, str | None]] = []
        for i, entry in enumerate(listed):
            where = f"versions[{i}]"
            entry = _object(entry, where)
            note = entry.get("note")
            if note is not None and not isinstance(note, str):
                raise BrightSkyResponseError(f"{where}.note must be a string or null")
            versions.append((_int(entry, "version", f"{where}.", 1), note))

        return cls(
            slug=_slug(obj, ""),
            site=_str(obj, "site", ""),
            current_version=_int(current, "version", "currentVersion.", 1),
            steps=steps,
            versions=versions,
        )


# ── writing ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunStep:
    """One step of a run report: did its element match, by which tier, and the outcome."""
    step_number: int
    matched: bool
    tier: str | None
    outcome: str

    def __post_init__(self) -> None:
        if self.outcome not in STEP_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(STEP_OUTCOMES)}")
        if self.tier is not None and len(self.tier) > MAX_TIER:
            raise ValueError(f"tier must be at most {MAX_TIER} characters")

    def to_json(self) -> dict:
        return {"stepNumber": self.step_number, "matched": self.matched,
                "tier": self.tier, "outcome": self.outcome}


@dataclass(frozen=True)
class RunReport:
    """The body of `POST /api/workflows/:slug/runs` (`ReportRunDto`)."""
    version: int
    steps: list[RunStep]
    result: str
    idempotency_key: str
    client: str = "stepper"

    def __post_init__(self) -> None:
        if len(self.steps) > MAX_STEPS:
            raise ValueError(f"a run report has at most {MAX_STEPS} steps")
        numbers = [s.step_number for s in self.steps]
        if len(set(numbers)) != len(numbers):
            raise ValueError("step numbers must be unique")
        if self.result not in RUN_RESULTS:
            raise ValueError(f"result must be one of {sorted(RUN_RESULTS)}")
        if not 1 <= len(self.idempotency_key) <= MAX_IDEMPOTENCY_KEY:
            raise ValueError(
                f"idempotency key must be 1 to {MAX_IDEMPOTENCY_KEY} characters")

    def to_json(self) -> dict:
        return {"version": self.version,
                "steps": [s.to_json() for s in self.steps],
                "result": self.result,
                "client": self.client,
                "idempotencyKey": self.idempotency_key}


@dataclass(frozen=True)
class Proposal:
    """The body of `POST /api/workflows/:slug/versions` (`ProposeVersionDto`)."""
    steps: list[dict]
    source: str
    #: Cut to MAX_NOTE characters, ending in "…", when longer.
    note: str

    def __post_init__(self) -> None:
        if self.source not in PROPOSAL_SOURCES:
            raise ValueError(f"source must be one of {sorted(PROPOSAL_SOURCES)}")
        if len(self.note) > MAX_NOTE:
            object.__setattr__(self, "note", self.note[:MAX_NOTE - 1] + "…")

    def to_json(self) -> dict:
        return {"steps": self.steps, "source": self.source, "note": self.note}


def new_idempotency_key() -> str:
    """A fresh key for one run's report (and its proposal's note)."""
    return "stepper-" + uuid.uuid4().hex
