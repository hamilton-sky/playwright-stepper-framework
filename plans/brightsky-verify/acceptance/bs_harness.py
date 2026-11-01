"""
Doubles shared by the brightsky-verify acceptance tests.

Nothing in here imports `stepper.brightsky` at module level: the feature does
not exist before it is built, and each test must fail on its own, inside its
body, rather than taking the whole file down at collection.

The wire shapes are bright-sky's (branch `claude/workflow-verify`):
`WorkflowDetail`, `VerificationQueueItem` and `WorkflowVersionView` in
workflow-store-api.views.ts, and the seeded pilot in pilot-workflows.ts.
NestJS error bodies are `{"statusCode", "message", "error"}`.
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

API_URL = "http://localhost:3001"
TOKEN = "bst_acceptance_secret_token_5f2c9a"
SLUG = "openlibrary-find-author"
SITE = "openlibrary.org"

HOME = "https://openlibrary.org/"
SEARCH = "https://openlibrary.org/search?q=The+Hobbit"
WORK = "https://openlibrary.org/works/OL262758W/The_Hobbit"
AUTHOR = "https://openlibrary.org/authors/OL26320A/J.R.R._Tolkien"

QUEUE_PATH = "/api/workflows/verification-queue"


def detail_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}"


def runs_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}/runs"


def versions_path(slug: str = SLUG) -> str:
    return f"/api/workflows/{slug}/versions"


# ── The seeded pilot, as bright-sky stores it ─────────────────────────────────

_PILOT_STEPS: list[dict] = [
    {
        "title": "Search for 'The Hobbit'",
        "explanation": (
            "On the Open Library home page, type 'The Hobbit' into the Search box "
            "and press Enter. A list of matching books will appear."
        ),
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/",
        "target": {
            "role": "textbox",
            "accessibleName": "Search",
            "selectors": [],
            "score": 0.8,
            "grounding": "current_page",
        },
        "expectedOutcome": {"kind": "url_change", "urlContains": "/search"},
    },
    {
        "title": "Open the book page",
        "explanation": (
            "In the search results, click the title 'The Hobbit'. This opens the "
            "book's page with its description and editions."
        ),
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/search",
        "target": {
            "role": "link",
            "accessibleName": "The Hobbit",
            "selectors": [],
            "score": 0.8,
            "grounding": "current_page",
        },
        "expectedOutcome": {"kind": "url_change", "urlContains": "/works/"},
    },
    {
        "title": "Open the author page",
        "explanation": (
            "On the book page, click the author's name, 'J.R.R. Tolkien'. This opens "
            "the author's page with their biography and other books."
        ),
        "expectedDomain": "openlibrary.org",
        "expectedUrl": "/works/",
        "target": {
            "role": "link",
            "accessibleName": "J.R.R. Tolkien",
            "selectors": [],
            "score": 0.8,
            "grounding": "current_page",
        },
        "expectedOutcome": {"kind": "url_change", "urlContains": "/authors/"},
    },
]


def pilot_steps() -> list[dict]:
    return copy.deepcopy(_PILOT_STEPS)


def version_view(n: int, note: str | None = None, status: str = "unverified",
                 source: str = "claude") -> dict:
    return {
        "id": f"ver-{n}",
        "version": n,
        "status": status,
        "source": source,
        "note": note,
        "createdAt": "2026-10-30T10:00:00.000Z",
        "createdBy": "seed",
    }


def detail_json(slug: str = SLUG, *, version: int = 1, steps: list[dict] | None = None,
                site: str = SITE, versions: list[dict] | None = None) -> dict:
    return {
        "id": f"wf-{slug}",
        "slug": slug,
        "site": site,
        "title": "Find a book's author on Open Library",
        "category": "research",
        "objective": "Find who wrote The Hobbit",
        "urlPatterns": [],
        "currentVersion": version_view(version),
        "currentSteps": pilot_steps() if steps is None else steps,
        "versions": versions if versions is not None
        else [version_view(n) for n in range(1, version + 1)],
    }


def queue_item(slug: str, version: int, *, site: str = SITE, runs: int = 0,
               created: str = "2026-10-01T00:00:00.000Z") -> dict:
    return {
        "workflowId": f"wf-{slug}",
        "slug": slug,
        "site": site,
        "versionId": f"ver-{slug}-{version}",
        "version": version,
        "source": "claude",
        "createdAt": created,
        "stepperRuns": runs,
    }


def run_view(slug: str = SLUG) -> dict:
    return {
        "id": "run-1",
        "workflowId": f"wf-{slug}",
        "versionId": "ver-1",
        "client": "stepper",
        "steps": [],
        "result": "failed",
        "idempotencyKey": "k",
        "createdAt": "2026-11-01T00:00:00.000Z",
        "updatedAt": "2026-11-01T00:00:00.000Z",
    }


def error_body(status: int, message: str) -> dict:
    names = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
             404: "Not Found", 422: "Unprocessable Entity",
             500: "Internal Server Error", 502: "Bad Gateway",
             503: "Service Unavailable"}
    return {"statusCode": status, "message": message, "error": names.get(status, "Error")}


# ── A fake BrightSky backend behind client.Transport ─────────────────────────

@dataclass
class Request:
    method: str
    url: str
    path: str
    headers: dict
    body: Any


class FakeBackend:
    """
    A recording `client.Transport`: `send(method, url, headers, body, timeout)`.

    Routes are (METHOD, path) -> list of responses, served in order; the last
    one repeats. A response is `(status, json_payload)`, an exception instance
    (raised, as a network failure would be), or a callable taking the Request.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list] = {}
        self.requests: list[Request] = []

    def on(self, method: str, path: str, *responses) -> "FakeBackend":
        self.routes[(method.upper(), path)] = list(responses)
        return self

    def send(self, method, url, headers, body, timeout):
        from stepper.brightsky.client import HttpResponse

        path = urlsplit(url).path
        try:
            parsed = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, AttributeError):
            parsed = body
        req = Request(method=str(method).upper(), url=url, path=path,
                      headers={str(k).lower(): v for k, v in dict(headers or {}).items()},
                      body=parsed)
        self.requests.append(req)

        queue = self.routes.get((req.method, path))
        if not queue:
            resp: Any = (404, error_body(404, f"Cannot {req.method} {path}"))
        elif len(queue) > 1:
            resp = queue.pop(0)
        else:
            resp = queue[0]
        if isinstance(resp, BaseException):
            raise resp
        if callable(resp):
            resp = resp(req)
        status, payload = resp
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return HttpResponse(status=status, body=raw)

    # Convenience views over what was sent.
    def sent(self, method: str, path: str) -> list[Request]:
        return [r for r in self.requests if r.method == method and r.path == path]

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.path) for r in self.requests]


def pilot_backend(*, version: int = 1, steps: list[dict] | None = None,
                  queue: list | None = None, proposed: int | None = None) -> FakeBackend:
    backend = FakeBackend()
    backend.on("GET", QUEUE_PATH, (200, queue if queue is not None else []))
    backend.on("GET", detail_path(), (200, detail_json(version=version, steps=steps)))
    backend.on("POST", runs_path(), (201, run_view()))
    backend.on("POST", versions_path(),
               (201, version_view(proposed if proposed is not None else version + 1,
                                  note="proposed", source="stepper")))
    return backend


def make_client(backend: FakeBackend, *, url: str = API_URL, token: str = TOKEN,
                sleeps: list | None = None):
    from stepper.brightsky.client import BrightSkyClient
    from stepper.brightsky.config import load_config

    config = load_config({"BRIGHTSKY_API_URL": url, "BRIGHTSKY_BRIDGE_TOKEN": token})
    sleep = sleeps.append if sleeps is not None else (lambda seconds: None)
    return BrightSkyClient(config, transport=backend, sleep=sleep)


def workflow_detail(steps: list[dict] | None = None, *, slug: str = SLUG,
                    site: str = SITE, version: int = 1):
    """A models.WorkflowDetail with the spec's named fields."""
    from stepper.brightsky.models import WorkflowDetail

    return WorkflowDetail(
        slug=slug, site=site, current_version=version,
        steps=pilot_steps() if steps is None else steps,
        versions=[(n, None) for n in range(1, version + 1)],
    )


def run_report(backend: FakeBackend, slug: str = SLUG) -> dict:
    posts = backend.sent("POST", runs_path(slug))
    assert len(posts) == 1, f"expected exactly one run report, got {len(posts)}"
    return posts[0].body


def steps_by_number(report: dict) -> dict[int, dict]:
    return {s["stepNumber"]: s for s in report["steps"]}


# ── A stub StepExecutor ───────────────────────────────────────────────────────

class StubExecutor:
    """
    `executor.StepExecutor`: `async execute(mapped, *, headless)`.

    plan holds one word per execute() call: "pass" (every step passed) or
    "fail" (the first step failed, the rest unchecked). The last word repeats.
    """

    def __init__(self, plan: list[str] | None = None) -> None:
        self.plan = list(plan or ["pass"])
        self.calls: list[dict] = []

    async def execute(self, mapped, *, headless):
        from stepper.brightsky.executor import ExecutedStep

        self.calls.append({"mapped": mapped, "headless": headless})
        word = self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        numbers = sorted(set(mapped.step_numbers.values()))
        out = []
        for i, n in enumerate(numbers):
            if word == "pass":
                out.append(ExecutedStep(step_number=n, outcome="passed", matched=True,
                                        tier="role", healed=False, healed_element=None,
                                        error=""))
            elif i == 0:
                out.append(ExecutedStep(step_number=n, outcome="failed", matched=False,
                                        tier=None, healed=False, healed_element=None,
                                        error="Element not found → not-found"))
            else:
                out.append(ExecutedStep(step_number=n, outcome="unchecked", matched=False,
                                        tier=None, healed=False, healed_element=None,
                                        error=""))
        return out


# ── The CLI, driven in-process through stepper.main.main() ────────────────────

@dataclass
class CliResult:
    code: int
    out: str
    err: str

    @property
    def lines(self) -> list[str]:
        return [line.strip() for line in self.out.splitlines() if line.strip()]


def run_cli(monkeypatch, capsys, args: list[str], *, backend: FakeBackend | None = None,
            executor=None, env: dict | None = None,
            ) -> CliResult:
    """
    `python3 -m stepper <args>` with verify.make_client and verify.make_executor
    monkeypatched (spec, Interfaces), so nothing reaches a network or a browser.
    """
    import stepper.brightsky.verify as verify
    from stepper.brightsky.client import BrightSkyClient

    environ = {"BRIGHTSKY_API_URL": API_URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    if env is not None:
        environ = env
    for name in ("BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    backend = backend if backend is not None else FakeBackend()
    executor = executor if executor is not None else StubExecutor()

    monkeypatch.setattr(
        verify, "make_client",
        lambda config: BrightSkyClient(config, transport=backend, sleep=lambda s: None),
    )
    monkeypatch.setattr(verify, "make_executor", lambda: executor)
    monkeypatch.setattr(sys, "argv", ["stepper", *args])

    from stepper.main import main

    capsys.readouterr()
    try:
        main()
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out, err = capsys.readouterr()
    return CliResult(code=code, out=out, err=err)


# ── Page, locator and resolver doubles for EngineExecutor ─────────────────────

def has(cfg: dict | None, needle: str) -> bool:
    return any(isinstance(v, str) and needle in v for v in (cfg or {}).values())


class FakeLocator:
    def __init__(self, page: "FakePage", name: str, *, click_to: str | None = None,
                 enter_to: str | None = None) -> None:
        self._page = page
        self.name = name
        self.click_to = click_to
        self.enter_to = enter_to
        self.value = ""

    @property
    def first(self) -> "FakeLocator":
        return self

    @property
    def last(self) -> "FakeLocator":
        return self

    def nth(self, i: int) -> "FakeLocator":
        return self

    async def click(self, *a, **kw):
        self._page.events.append(("click", self.name))
        if self.click_to:
            self._page.url = self.click_to

    async def dblclick(self, *a, **kw):
        await self.click()

    async def fill(self, value, *a, **kw):
        self._page.events.append(("fill", self.name, value))
        self.value = value
        self._page.focused = self

    async def type(self, value, *a, **kw):
        await self.fill(value)

    async def press_sequentially(self, value, *a, **kw):
        await self.fill(value)

    async def press(self, key, *a, **kw):
        self._page.events.append(("press", self.name, key))
        if key == "Enter" and self.enter_to:
            self._page.url = self.enter_to

    async def input_value(self, *a, **kw):
        return self.value

    async def evaluate(self, script, *a, **kw):
        if "click" in str(script):
            await self.click()
        return None

    async def scroll_into_view_if_needed(self, *a, **kw):
        return None

    async def hover(self, *a, **kw):
        return None

    async def focus(self, *a, **kw):
        self._page.focused = self

    async def wait_for(self, *a, **kw):
        return None

    async def is_visible(self, *a, **kw):
        return True

    async def is_enabled(self, *a, **kw):
        return True

    async def is_hidden(self, *a, **kw):
        return False

    async def count(self):
        return 1

    async def all(self):
        return [self]

    async def inner_text(self, *a, **kw):
        return self.name

    async def text_content(self, *a, **kw):
        return self.name

    async def get_attribute(self, *a, **kw):
        return None

    async def bounding_box(self, *a, **kw):
        return None


class _AbsentLocator(FakeLocator):
    async def count(self):
        return 0

    async def all(self):
        return []

    async def is_visible(self, *a, **kw):
        return False


class _Keyboard:
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    async def press(self, key, *a, **kw):
        if self._page.focused is not None:
            await self._page.focused.press(key)

    async def type(self, *a, **kw):
        return None


class FakePage:
    """Just enough of a Playwright Page: a URL that real actions move."""

    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.events: list[tuple] = []
        self.focused: FakeLocator | None = None
        self.keyboard = _Keyboard(self)
        self.mouse = _Keyboard(self)

    async def goto(self, url, *a, **kw):
        self.events.append(("goto", url))
        self.url = url
        return None

    async def wait_for_url(self, url, *a, **kw):
        if callable(url):
            ok = url(self.url)
        elif hasattr(url, "search"):
            ok = bool(url.search(self.url))
        else:
            import fnmatch
            ok = fnmatch.fnmatch(self.url, str(url)) or str(url) == self.url
        if not ok:
            from playwright.async_api import TimeoutError as PlaywrightTimeout
            raise PlaywrightTimeout(f"wait_for_url({url!r}) timed out on {self.url}")

    async def wait_for_load_state(self, *a, **kw):
        return None

    async def wait_for_timeout(self, *a, **kw):
        return None

    async def wait_for_selector(self, *a, **kw):
        return None

    async def query_selector(self, *a, **kw):
        return None

    async def query_selector_all(self, *a, **kw):
        return []

    async def screenshot(self, *a, **kw):
        return b""

    async def title(self):
        return "Open Library"

    async def content(self):
        return "<html><body></body></html>"

    async def evaluate(self, *a, **kw):
        return None

    async def set_viewport_size(self, *a, **kw):
        return None

    def is_closed(self):
        return False

    def _absent(self, *a, **kw):
        return _AbsentLocator(self, "absent")

    locator = get_by_role = get_by_text = get_by_placeholder = get_by_label = _absent
    get_by_test_id = get_by_title = get_by_alt_text = _absent

    @property
    def context(self):
        return self


@dataclass
class Rule:
    name: str
    matches: Callable[[dict], bool]
    click_to: str | None = None
    enter_to: str | None = None
    misses: int = 0


class FakeResolver:
    """
    A resolver double: answers found for a cfg a rule matches, not-found
    otherwise, and records every lookup with its `strict` flag.
    """

    def __init__(self, page: FakePage, rules: list[Rule]) -> None:
        self._page = page
        self.rules = rules
        self.calls: list[dict] = []

    def set_context_description(self, description) -> None:
        return None

    async def resolve(self, page, cfg, description="", *args, **kwargs):
        from stepper.engine.interfaces import ResolveResult

        cfg = dict(cfg or {})
        self.calls.append({"cfg": cfg, "strict": kwargs.get("strict", False),
                           "description": description})
        for rule in self.rules:
            if rule.matches(cfg):
                if rule.misses > 0:
                    rule.misses -= 1
                    break
                locator = FakeLocator(self._page, rule.name, click_to=rule.click_to,
                                      enter_to=rule.enter_to)
                return ResolveResult(found=True, locator=locator, confidence=0.95,
                                     method="role")
        return ResolveResult(found=False, locator=None, confidence=0.0, method="not-found")


def is_search_box(cfg: dict) -> bool:
    return cfg.get("role") == "textbox" and has(cfg, "Search")


def is_hobbit_link(cfg: dict) -> bool:
    return cfg.get("role") == "link" and has(cfg, "The Hobbit")


def is_tolkien_link(cfg: dict) -> bool:
    return cfg.get("role") == "link" and has(cfg, "Tolkien")


HEALED_LINK = "#healed-link"


def pilot_rules(*, broken: tuple[int, ...] = (), enter_to: str | None = SEARCH) -> list[Rule]:
    """The pilot's three elements; the step numbers in `broken` are not on the page."""
    rules = []
    if 1 not in broken:
        rules.append(Rule("search box", is_search_box, enter_to=enter_to))
    if 2 not in broken:
        rules.append(Rule("hobbit link", is_hobbit_link, click_to=WORK))
    if 3 not in broken:
        rules.append(Rule("tolkien link", is_tolkien_link, click_to=AUTHOR))
    # Where the healed elements live.
    rules.append(Rule("healed hobbit link", lambda c: has(c, HEALED_LINK), click_to=WORK))
    rules.append(Rule("search placeholder", lambda c: c.get("placeholder") == "Search",
                      enter_to=enter_to))
    rules.append(Rule("hobbit text", lambda c: c.get("text") == "The Hobbit" and
                      len(c) <= 2 and "role" not in c, click_to=WORK))
    return rules


class Probe:
    """
    Stand-in for DOMSnapshotCascade.capture(page, step, *, skip_direct=False).

    direct(step) gives the embed_direct cfg for a step (None for none); with
    skip_direct=True, or with no cfg, it answers an embed_candidates payload
    whose content is unique per call.
    """

    def __init__(self, events: list, direct: Callable[[Any], dict | None] | None = None):
        self.events = events
        self.direct = direct or (lambda step: None)
        self.calls: list[dict] = []

    async def capture(self, page, step, *, skip_direct=False, **kw):
        from stepper.engine.healer.interfaces import DomPayload

        self.calls.append({"step": step, "skip_direct": skip_direct})
        cfg = None if skip_direct else self.direct(step)
        if cfg is not None:
            payload = DomPayload(strategy_used="embed_direct", content="", healed_cfg=dict(cfg))
        else:
            n = len(self.calls)
            payload = DomPayload(
                strategy_used="embed_candidates",
                content=f"page-snapshot-{n} candidates link The Hobbit healed-link",
                healed_cfg=None, token_estimate=12,
            )
        self.events.append(("capture", step, skip_direct, payload))
        return payload


def reply_for(step, element: dict | None) -> str:
    """One replacement step, copying the failed step's fields (AiHealer rule 4)."""
    return json.dumps([{
        "action": step.action,
        "description": step.description,
        "url": step.url,
        "element": element or {},
        "input_value": step.input_value,
        "wait_for": step.wait_for,
        "extra": dict(step.extra or {}),
    }])


def last_captured_step(events: list):
    for event in reversed(events):
        if event[0] == "capture":
            return event[1]
    raise AssertionError("the AI was asked to heal before the page was probed")


class FakeAI:
    """
    An `ai_service` double: `async chat(prompt, task_type="classify", system="")`.

    elements holds the element cfg each successive reply proposes; when it runs
    out, replies propose an element that is not on the page.
    """

    def __init__(self, events: list, elements: list[dict] | None = None) -> None:
        self.events = events
        self.elements = list(elements or [])
        self.task_types: list[str] = []
        self.prompts: list[str] = []

    async def chat(self, prompt, task_type="classify", system=""):
        self.task_types.append(task_type)
        self.prompts.append(prompt)
        self.events.append(("ai", task_type, prompt))
        n = len(self.task_types)
        element = self.elements.pop(0) if self.elements else {"css": f"#not-on-page-{n}"}
        return reply_for(last_captured_step(self.events), element)


def patch_probes(monkeypatch, probe: Probe, visual: str | None = None) -> None:
    from stepper.engine.healer.dom_snapshot import DOMSnapshotCascade
    from stepper.engine.healer.visual_bridge import VisualBridge

    monkeypatch.setattr(DOMSnapshotCascade, "capture", staticmethod(probe.capture))

    async def _check(page, step, *a, **kw):
        return visual

    monkeypatch.setattr(VisualBridge, "check", staticmethod(_check))


@dataclass
class EngineWorld:
    page: FakePage
    resolver: FakeResolver
    probe: Probe
    ai: FakeAI | None
    events: list = field(default_factory=list)
    executor: Any = None


def engine_world(monkeypatch, *, broken: tuple[int, ...] = (),
                 direct: Callable[[Any], dict | None] | None = None,
                 ai_elements: list[dict] | None = None, with_ai: bool = True,
                 visual: str | None = None, enter_to: str | None = SEARCH,
                 rules: list[Rule] | None = None) -> EngineWorld:
    """An EngineExecutor over the page double, the resolver double and the probes."""
    from stepper.brightsky.executor import EngineExecutor

    events: list = []
    page = FakePage()
    resolver = FakeResolver(page, rules if rules is not None
                            else pilot_rules(broken=broken, enter_to=enter_to))
    probe = Probe(events, direct)
    patch_probes(monkeypatch, probe, visual)
    ai = FakeAI(events, ai_elements) if with_ai else None
    if ai is not None:
        executor = EngineExecutor(page, resolver, ai_service=ai)
    else:
        executor = EngineExecutor(page, resolver)
    return EngineWorld(page=page, resolver=resolver, probe=probe, ai=ai,
                       events=events, executor=executor)


def is_step(n: int) -> Callable[[Any], bool]:
    """Which pilot step a StepConfig the heal loop probes is, by its element."""
    checks = {1: is_search_box, 2: is_hobbit_link, 3: is_tolkien_link}
    return lambda step: checks[n](dict(step.element or {}))
