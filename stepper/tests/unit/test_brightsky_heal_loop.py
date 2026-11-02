"""
The bar's "a missing element triggers the heal cascade", proven through the
real engine with no browser and no network (ticket 06).

`verify_slug` runs a pilot-like workflow, served by a stubbed `Transport`, on
an `EngineExecutor` over a fake page: the real action registry, StepRunner,
AiHealer and expectation hook. Only the public seams are doubled (spec.md,
Interfaces): the resolver misses the stored target of step 2, link "The
Hobbit", and finds the healed one; the AI double records each `task_type`;
and the heal loop's two page probes, `DOMSnapshotCascade.capture` and
`VisualBridge.check`, are monkeypatched.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest

from stepper.brightsky.client import BrightSkyClient, HttpResponse
from stepper.brightsky.config import BrightSkyConfig
from stepper.brightsky.executor import EngineExecutor
from stepper.brightsky.verify import verify_slug
from stepper.engine.healer.dom_snapshot import DOMSnapshotCascade
from stepper.engine.healer.interfaces import DomPayload
from stepper.engine.healer.visual_bridge import VisualBridge
from stepper.engine.interfaces import ResolveResult

TOKEN = "bst_heal_loop_secret_token_6e2b8d"
URL = "https://bright-sky.example.com"
SLUG = "openlibrary-find-author"
QUEUE = "/api/workflows/verification-queue"
DETAIL = f"/api/workflows/{SLUG}"
RUNS = f"/api/workflows/{SLUG}/runs"
VERSIONS = f"/api/workflows/{SLUG}/versions"

HOME = "https://openlibrary.org/"
SEARCH = "https://openlibrary.org/search?q=The+Hobbit"
WORK = "https://openlibrary.org/works/OL262758W/The_Hobbit"
AUTHOR = "https://openlibrary.org/authors/OL26320A/J.R.R._Tolkien"

SEARCH_BOX = {"role": "textbox", "name": "Search"}
STORED = {"role": "link", "name": "The Hobbit"}
FOUND = {"role": "link", "name": "The Hobbit (1937)", "css": "a.result"}
TOLKIEN = {"role": "link", "name": "J.R.R. Tolkien"}
STEP_2 = "Step 2: Open the book page"


def _target(role: str, name: str) -> dict:
    return {"role": role, "accessibleName": name, "selectors": [], "score": 0.8,
            "grounding": "current_page"}


def pilot_steps() -> list[dict]:
    return [
        {"title": "Search for 'The Hobbit'", "explanation": "Type it and press Enter.",
         "expectedDomain": "openlibrary.org", "expectedUrl": "/",
         "target": _target("textbox", "Search"),
         "expectedOutcome": {"kind": "url_change", "urlContains": "/search"}},
        {"title": "Open the book page", "explanation": "Click the title.",
         "expectedDomain": "openlibrary.org", "expectedUrl": "/search",
         "target": _target("link", "The Hobbit"),
         "expectedOutcome": {"kind": "url_change", "urlContains": "/works/"}},
        {"title": "Open the author page", "explanation": "Click the author's name.",
         "expectedDomain": "openlibrary.org", "expectedUrl": "/works/",
         "target": _target("link", "J.R.R. Tolkien"),
         "expectedOutcome": {"kind": "url_change", "urlContains": "/authors/"}},
    ]


# ── the backend ───────────────────────────────────────────────────────────────

@dataclass
class Sent:
    method: str
    path: str
    body: dict | None


class StubTransport:
    """Serves the pilot and records every request in order."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.responses = {
            ("GET", QUEUE): (200, []),
            ("GET", DETAIL): (200, {
                "slug": SLUG, "site": "openlibrary.org",
                "currentVersion": {"version": 1, "note": None},
                "currentSteps": pilot_steps(),
                "versions": [{"version": 1, "note": None}]}),
            ("POST", RUNS): (201, {"id": "run-1"}),
            ("POST", VERSIONS): (201, {"version": 2}),
        }

    def send(self, method, url, headers, body, timeout):
        path = urlsplit(url).path
        self.sent.append(Sent(method, path, json.loads(body) if body else None))
        status, payload = self.responses[(method, path)]
        return HttpResponse(status=status, body=json.dumps(payload).encode())

    def posts(self) -> list[Sent]:
        return [s for s in self.sent if s.method == "POST"]


# ── the page, the resolver and the AI ─────────────────────────────────────────

class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"

    async def goto(self, url, **kwargs):
        self.url = url


class FakeLocator:
    """Clicking (or pressing Enter in) the element moves the page to `goes_to`."""

    def __init__(self, page: FakePage, goes_to: str) -> None:
        self._page = page
        self._goes_to = goes_to

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self, timeout=None, force=False):
        self._page.url = self._goes_to

    async def fill(self, value, timeout=None):
        return None

    async def press(self, key):
        if key == "Enter":
            self._page.url = self._goes_to


class FakeResolver:
    """Finds only the cfgs on the page (the stored "The Hobbit" link is not)."""

    def __init__(self, page: FakePage) -> None:
        self._on_page = [(SEARCH_BOX, SEARCH), (FOUND, WORK), (TOLKIEN, AUTHOR)]
        self._page = page
        self.calls: list[dict] = []

    def set_context_description(self, description):
        return None

    async def resolve(self, page, cfg, step_description="", *, strict=False, action=None):
        self.calls.append({"cfg": dict(cfg), "strict": strict})
        for element, goes_to in self._on_page:
            if dict(cfg) == element:
                return ResolveResult(found=True, locator=FakeLocator(self._page, goes_to),
                                     confidence=0.95, method="role")
        return ResolveResult(found=False, method="none")


class RecordingAI:
    """Records each task_type; reply i proposes `elements[i]`, else an element not on the page."""

    def __init__(self, elements: list[dict] | None = None) -> None:
        self._elements = list(elements or [])
        self.task_types: list[str] = []

    async def chat(self, prompt, task_type="classify", system=""):
        self.task_types.append(task_type)
        n = len(self.task_types)
        element = (self._elements[n - 1] if n <= len(self._elements)
                   else {"css": f"a.miss-{n}"})
        return json.dumps([{"action": "click", "description": STEP_2,
                            "element": element, "extra": {"strict": True}}])


@pytest.fixture
def probes(monkeypatch):
    """Patch both page probes; the setter picks step 2's embed_direct cfg (or none)."""
    async def _no_bridge(page, step):
        return None

    monkeypatch.setattr(VisualBridge, "check", _no_bridge)

    def _set(direct_cfg: dict | None):
        async def _capture(page, step, *, skip_direct=False):
            if direct_cfg is not None and not skip_direct:
                return DomPayload("embed_direct", "", dict(direct_cfg), 0)
            return DomPayload("embed_candidates", '{"candidates": ["a.result"]}', None, 20)

        monkeypatch.setattr(DOMSnapshotCascade, "capture", _capture)
    return _set


async def _run(ai: RecordingAI) -> tuple:
    transport = StubTransport()
    client = BrightSkyClient(BrightSkyConfig(api_url=URL, token=TOKEN),
                             transport=transport, sleep=lambda seconds: None)
    page = FakePage()
    resolver = FakeResolver(page)
    outcome = await verify_slug(client, EngineExecutor(page, resolver, ai_service=ai), SLUG)
    return outcome, transport, resolver


def _by_number(report: dict) -> dict[int, dict]:
    return {s["stepNumber"]: s for s in report["steps"]}


# ── the cases ─────────────────────────────────────────────────────────────────

async def test_an_embed_direct_heal_is_reported_failed_then_proposed_from_stepper(probes):
    probes(FOUND)
    ai = RecordingAI()

    outcome, transport, resolver = await _run(ai)

    assert ai.task_types == []
    assert {"cfg": STORED, "strict": True} in resolver.calls
    runs, versions = transport.posts()
    assert (runs.path, versions.path) == (RUNS, VERSIONS)
    report = runs.body
    assert report["result"] == "failed"
    steps = _by_number(report)
    assert steps[2] == {"stepNumber": 2, "matched": False, "tier": "embed_direct",
                        "outcome": "failed"}
    assert steps[1]["outcome"] == "passed" and steps[3]["outcome"] == "passed"

    proposal = versions.body
    fetched = pilot_steps()
    assert proposal["source"] == "stepper"
    assert proposal["steps"][0] == fetched[0]
    assert proposal["steps"][2] == fetched[2]
    target = proposal["steps"][1]["target"]
    assert target["role"] == "link"
    assert target["accessibleName"] == "The Hobbit (1937)"
    assert target["selectors"] == ["a.result"]
    assert report["idempotencyKey"] in proposal["note"]
    assert "step 2" in proposal["note"]
    assert outcome.status == "healed"
    assert outcome.proposed_version == 2


async def test_a_missed_embed_direct_then_two_cheap_misses_heal_on_the_big_model(probes):
    probes({"css": "a.stale"})
    ai = RecordingAI([{"css": "a.miss-1"}, {"css": "a.miss-2"}, dict(FOUND)])

    outcome, transport, _ = await _run(ai)

    assert ai.task_types == ["heal", "heal", "heal_big"]
    runs, versions = transport.posts()
    assert runs.body["result"] == "failed"
    assert _by_number(runs.body)[2]["tier"] == "big"
    assert versions.body["source"] == "haiku"
    assert versions.body["steps"][1]["target"]["accessibleName"] == "The Hobbit (1937)"
    assert outcome.status == "healed"


async def test_when_every_ai_reply_misses_the_run_is_failed_and_nothing_is_proposed(probes):
    probes({"css": "a.stale"})
    ai = RecordingAI()

    outcome, transport, _ = await _run(ai)

    assert ai.task_types == ["heal", "heal", "heal_big"]
    [runs] = transport.posts()
    assert runs.path == RUNS
    assert runs.body["result"] == "failed"
    steps = _by_number(runs.body)
    assert steps[2]["outcome"] == "failed"
    assert steps[3]["outcome"] == "unchecked"
    assert outcome.status == "failed"
    assert outcome.proposed_version is None
