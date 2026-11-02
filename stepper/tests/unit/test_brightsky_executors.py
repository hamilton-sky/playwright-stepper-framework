"""
Tests for the two StepExecutors in stepper/brightsky/executor.py (ticket 13).

- `EngineExecutor` runs a mapped workflow on a real StepRunner with the real
  action registry and a real AiHealer, over a page and resolver double. The
  heal loop's two page probes, `DOMSnapshotCascade.capture` and
  `VisualBridge.check`, are monkeypatched, so nothing launches.
- `PipelineExecutor` drives `stepper.main`'s pipeline; here every pipeline
  function is monkeypatched, so these pin the wiring: the RunConfig it asks
  for, the hook it attaches, the order and the cleanup.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from stepper.brightsky.executor import (
    EngineExecutor, ExpectationHook, PipelineExecutor, RecordingResolver, StepExecutor,
)
from stepper.brightsky.mapping import MappedWorkflow, StepExpectation
from stepper.engine.healer.dom_snapshot import DOMSnapshotCascade
from stepper.engine.healer.interfaces import DomPayload, HealerStrategy, HealingError
from stepper.engine.healer.visual_bridge import VisualBridge
from stepper.engine.interfaces import ResolveResult, StepConfig, StepResult


STORED = {"role": "link", "name": "The Hobbit"}
FOUND = {"role": "link", "name": "The Hobbit (1937)", "css": "a.result"}
DESCRIPTION = "Open 'The Hobbit'"
AI_KEYS = ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")


# ── Doubles ───────────────────────────────────────────────────────────────────

class FakeLocator:
    def __init__(self):
        self.clicks = 0

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self, timeout=None, force=False):
        self.clicks += 1

    async def fill(self, value, timeout=None):
        return None


class FakePage:
    url = "https://openlibrary.org/search?q=the+hobbit"


class FakeResolver:
    """Finds only the element cfgs in `finds`; records every resolve."""

    def __init__(self, finds=()):
        self._finds = [dict(f) for f in finds]
        self.calls: list[dict] = []
        self.locator = FakeLocator()

    def set_context_description(self, description):
        return None

    async def resolve(self, page, cfg, step_description="", *, strict=False, action=None):
        self.calls.append({"cfg": dict(cfg), "strict": strict, "action": action})
        if dict(cfg) in self._finds:
            return ResolveResult(found=True, locator=self.locator,
                                 confidence=0.95, method="css")
        return ResolveResult(found=False, method="none")


class RecordingAI:
    """AIService double: records each task_type; every reply is a miss."""

    def __init__(self):
        self.task_types: list[str] = []

    async def chat(self, prompt, task_type="classify", system=""):
        self.task_types.append(task_type)
        return json.dumps([{"action": "click", "description": DESCRIPTION,
                            "element": {"css": f"a.miss-{len(self.task_types)}"}}])


class NavigatingAI:
    """AIService double whose heal reply sends the run off-site."""

    def __init__(self):
        self.task_types: list[str] = []

    async def chat(self, prompt, task_type="classify", system=""):
        self.task_types.append(task_type)
        return json.dumps([{"action": "navigate", "description": DESCRIPTION,
                            "url": "https://evil.example/steal"}])


class FoundAI:
    """AIService double whose heal reply is the mapped click on the found element."""

    def __init__(self, extra_steps=()):
        self.task_types: list[str] = []
        self._extra = list(extra_steps)

    async def chat(self, prompt, task_type="classify", system=""):
        self.task_types.append(task_type)
        return json.dumps([{"action": "click", "description": DESCRIPTION,
                            "element": dict(FOUND), "extra": {"strict": True}},
                           *self._extra])


class GotoPage(FakePage):
    def __init__(self):
        self.visited: list[str] = []

    async def goto(self, url, **kwargs):
        self.visited.append(url)


class FakeCapture:
    """Stands in for DOMSnapshotCascade.capture: an embed_direct cfg, or none."""

    def __init__(self, cfg):
        self._cfg = cfg
        self.calls: list[dict] = []

    async def __call__(self, page, step, **kwargs):
        self.calls.append(kwargs)
        if self._cfg is not None and not kwargs.get("skip_direct", False):
            return DomPayload("embed_direct", "", dict(self._cfg), 0)
        return DomPayload("scoped", '{"best_match": "PAGE"}', None, 40)


@pytest.fixture
def probes(monkeypatch):
    """Patch both page probes; returns a setter for the capture's cfg."""
    async def _no_bridge(page, step):
        return None

    monkeypatch.setattr(VisualBridge, "check", _no_bridge)

    def _set(cfg):
        capture = FakeCapture(cfg)
        monkeypatch.setattr(DOMSnapshotCascade, "capture", capture)
        return capture
    return _set


def mapped(expectation: StepExpectation | None = None) -> MappedWorkflow:
    click = StepConfig(action="click", description=DESCRIPTION,
                       element=dict(STORED), extra={"strict": True})
    exp = expectation or StepExpectation(start_url=None, match_mode=None,
                                         outcome_kind=None, outcome_element=None,
                                         url_contains=None)
    return MappedWorkflow(steps=[click], step_numbers={DESCRIPTION: 1},
                          expectations={DESCRIPTION: exp})


# ── EngineExecutor ────────────────────────────────────────────────────────────

def test_engine_executor_is_a_step_executor():
    assert isinstance(EngineExecutor(FakePage(), FakeResolver(), ai_service=RecordingAI()),
                      StepExecutor)


async def test_engine_an_embed_direct_cfg_that_resolves_heals_with_no_ai_call(probes):
    capture = probes(FOUND)
    resolver = FakeResolver(finds=[FOUND])
    ai = RecordingAI()

    steps = await EngineExecutor(FakePage(), resolver, ai_service=ai).execute(
        mapped(), headless=True)

    assert resolver.calls[0]["cfg"] == STORED
    assert resolver.calls[0]["strict"] is True
    assert resolver.calls[1]["cfg"] == FOUND
    assert len(steps) == 1
    assert steps[0].outcome == "failed"
    assert steps[0].healed is True
    assert steps[0].tier == "embed_direct"
    assert steps[0].matched is False
    assert ai.task_types == []
    assert len(capture.calls) == 1
    assert resolver.locator.clicks == 1


async def test_engine_a_missing_cfg_and_missing_ai_replies_go_cheap_cheap_big(probes):
    capture = probes({"css": "a.stale"})
    resolver = FakeResolver(finds=[FOUND])
    ai = RecordingAI()

    steps = await EngineExecutor(FakePage(), resolver, ai_service=ai).execute(
        mapped(), headless=True)

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert [kw.get("skip_direct", False) for kw in capture.calls] == [False, True, True, True]
    assert steps[0].outcome == "failed"
    assert steps[0].healed is False
    assert steps[0].matched is False
    assert steps[0].tier is None


async def test_engine_without_an_ai_service_or_keys_leaves_a_no_cfg_step_failed(
        probes, monkeypatch):
    for key in AI_KEYS:
        monkeypatch.delenv(key, raising=False)
    probes(None)
    resolver = FakeResolver(finds=[FOUND])

    steps = await EngineExecutor(FakePage(), resolver).execute(mapped(), headless=True)

    assert steps[0].outcome == "failed"
    assert steps[0].healed is False
    assert [c["cfg"] for c in resolver.calls] == [STORED]


async def test_engine_a_stored_target_that_resolves_passes_with_its_tier(probes):
    capture = probes(FOUND)
    resolver = FakeResolver(finds=[STORED])
    ai = RecordingAI()

    steps = await EngineExecutor(FakePage(), resolver, ai_service=ai).execute(
        mapped(), headless=False)

    assert steps[0].outcome == "passed"
    assert steps[0].matched is True
    assert steps[0].tier == "css"
    assert capture.calls == []
    assert ai.task_types == []


async def test_engine_attaches_the_expectation_hook(probes):
    probes(None)
    resolver = FakeResolver(finds=[STORED])
    exp = StepExpectation(start_url="/works", match_mode=None, outcome_kind=None,
                          outcome_element=None, url_contains=None)

    steps = await EngineExecutor(FakePage(), resolver, ai_service=RecordingAI()).execute(
        mapped(exp), headless=True)

    assert resolver.calls == []
    assert steps[0].outcome == "failed"
    assert steps[0].error.startswith("not on the expected page")


async def test_engine_rejects_a_heal_reply_that_navigates_off_site(probes):
    probes(None)
    page = GotoPage()
    resolver = FakeResolver(finds=[FOUND])
    ai = NavigatingAI()

    steps = await EngineExecutor(page, resolver, ai_service=ai).execute(
        mapped(), headless=True)

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert page.visited == []
    assert steps[0].outcome == "failed"
    assert steps[0].healed is False


async def test_engine_rejects_a_heal_reply_that_adds_steps(probes):
    probes(None)
    page = GotoPage()
    resolver = FakeResolver(finds=[FOUND])
    ai = FoundAI(extra_steps=[{"action": "screenshot", "description": "x",
                               "extra": {"filename": "../../leak.png"}}])

    steps = await EngineExecutor(page, resolver, ai_service=ai).execute(
        mapped(), headless=True)

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert resolver.locator.clicks == 0
    assert steps[0].healed is False


async def test_engine_accepts_a_heal_reply_that_only_changes_the_element(probes):
    probes(None)
    resolver = FakeResolver(finds=[FOUND])
    ai = FoundAI()

    steps = await EngineExecutor(FakePage(), resolver, ai_service=ai).execute(
        mapped(), headless=True)

    assert ai.task_types == ["heal"]
    assert steps[0].healed is True
    assert steps[0].tier == "cheap"
    assert resolver.locator.clicks == 1


# ── PipelineExecutor ──────────────────────────────────────────────────────────

class PassThroughHealer(HealerStrategy):
    """The pipeline's own healer, as build_healer would give: returns `reply`."""

    def __init__(self, reply):
        self.reply = reply

    async def heal(self, step, error, dom, **kwargs):
        return list(self.reply)


class FakeRunner:
    def __init__(self):
        self.hooks: list[tuple] = []
        self._healer = PassThroughHealer(
            [StepConfig(action="navigate", description=DESCRIPTION,
                        url="https://evil.example/steal")])

    def add_hook(self, domain, hook):
        self.hooks.append((domain, hook))
        return self


class FakeSessions:
    def __init__(self):
        self.closed = 0

    async def close_all(self):
        self.closed += 1


@pytest.fixture
def pipeline(monkeypatch):
    """`stepper.main`'s pipeline functions, recorded; `world.raise_in` picks a failure."""
    from stepper import main

    world = SimpleNamespace(order=[], cfg=None, workflow=None, resolver=None,
                            sessions=FakeSessions(), runner=FakeRunner(),
                            raise_in=None, results=[])
    inner = FakeResolver()

    def fake_build_settings(cfg):
        return SimpleNamespace(use_visual_ai=False)

    def fake_build_resolver(use_visual_ai):
        world.order.append("build_resolver")
        return inner

    def fake_prepare_run(cfg, resolver=None):
        world.order.append("prepare_run")
        world.cfg = cfg
        world.resolver = resolver
        world.workflow = json.loads(Path(cfg.workflow_path).read_text(encoding="utf-8"))
        if world.raise_in == "prepare_run":
            raise main.DomainNotReadyError("web: no browser", {"web": ["no browser"]})
        return SimpleNamespace(cfg=cfg, resolver=resolver)

    def fake_build_session_set(prepared, shared=None):
        world.order.append("build_session_set")
        return world.sessions

    async def fake_build_pipeline(prepared, sessions, observers=None):
        world.order.append("build_pipeline")
        assert sessions is world.sessions
        return SimpleNamespace(runner=world.runner, prepared=prepared)

    async def fake_execute_pipeline(pipe):
        world.order.append("execute_pipeline")
        if world.raise_in == "execute_pipeline":
            raise RuntimeError("browser crashed")
        return world.results

    monkeypatch.setattr(main, "build_settings", fake_build_settings)
    monkeypatch.setattr(main, "build_resolver", fake_build_resolver)
    monkeypatch.setattr(main, "prepare_run", fake_prepare_run)
    monkeypatch.setattr(main, "build_session_set", fake_build_session_set)
    monkeypatch.setattr(main, "build_pipeline", fake_build_pipeline)
    monkeypatch.setattr(main, "execute_pipeline", fake_execute_pipeline)
    return world


def test_pipeline_executor_is_a_step_executor():
    assert isinstance(PipelineExecutor(), StepExecutor)


@pytest.mark.parametrize("headless", [True, False])
async def test_pipeline_runs_a_strict_heal_without_the_cache(pipeline, headless):
    workflow = mapped()
    pipeline.results = [StepResult(step=workflow.steps[0], status="passed")]

    steps = await PipelineExecutor().execute(workflow, headless=headless)

    cfg = pipeline.cfg
    assert cfg.max_heal_attempts == 3
    assert cfg.use_heal_cache is False
    assert cfg.strict_heal_order is True
    assert cfg.headless is headless
    assert pipeline.order == ["build_resolver", "prepare_run", "build_session_set",
                              "build_pipeline", "execute_pipeline"]
    assert isinstance(pipeline.resolver, RecordingResolver)
    assert [d for d, _ in pipeline.runner.hooks] == ["web"]
    assert isinstance(pipeline.runner.hooks[0][1], ExpectationHook)
    assert pipeline.sessions.closed == 1
    assert [s.step_number for s in steps] == [1]
    assert steps[0].outcome == "passed"


async def test_pipeline_writes_the_mapped_steps_as_a_web_workflow(pipeline):
    workflow = mapped()

    await PipelineExecutor().execute(workflow, headless=True)

    assert pipeline.workflow["domain"] == "web"
    assert isinstance(pipeline.workflow["name"], str) and pipeline.workflow["name"]
    assert pipeline.workflow["steps"] == [asdict(s) for s in workflow.steps]


async def test_pipeline_closes_the_sessions_when_the_run_raises(pipeline):
    pipeline.raise_in = "execute_pipeline"

    with pytest.raises(RuntimeError, match="browser crashed"):
        await PipelineExecutor().execute(mapped(), headless=True)

    assert pipeline.sessions.closed == 1
    assert not Path(pipeline.cfg.workflow_path).exists()
    assert not Path(pipeline.cfg.workflow_path).parent.exists()


async def test_pipeline_leaves_no_temp_file_behind(pipeline):
    await PipelineExecutor().execute(mapped(), headless=True)

    assert not Path(pipeline.cfg.workflow_path).exists()
    assert not Path(pipeline.cfg.workflow_path).parent.exists()


async def test_pipeline_a_domain_that_is_not_ready_propagates_before_anything_opens(pipeline):
    from stepper.bootstrap.session import DomainNotReadyError

    pipeline.raise_in = "prepare_run"

    with pytest.raises(DomainNotReadyError):
        await PipelineExecutor().execute(mapped(), headless=True)

    assert "build_session_set" not in pipeline.order
    assert pipeline.sessions.closed == 0
    assert not Path(pipeline.cfg.workflow_path).parent.exists()


async def test_pipeline_limits_the_runners_healer_to_element_changes(pipeline):
    workflow = mapped()

    await PipelineExecutor().execute(workflow, headless=True)

    healer = pipeline.runner._healer
    assert not isinstance(healer, PassThroughHealer)
    dom = DomPayload("scoped", "PAGE", None, 1)
    with pytest.raises(HealingError):
        await healer.heal(workflow.steps[0], "not found", dom)
    found = StepConfig(action="click", description=DESCRIPTION,
                       element=dict(FOUND), extra={"strict": True})
    healer._inner.reply = [found]
    assert await healer.heal(workflow.steps[0], "not found", dom) == [found]


async def test_pipeline_refuses_a_temp_dir_that_names_a_site(pipeline, tmp_path, monkeypatch):
    import tempfile

    site_tmp = tmp_path / "sites" / "openlibrary" / "tmp"
    site_tmp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(site_tmp))

    with pytest.raises(RuntimeError, match="site"):
        await PipelineExecutor().execute(mapped(), headless=True)

    assert pipeline.order == []
    assert list(site_tmp.iterdir()) == []


def test_importing_the_executor_does_not_import_the_pipeline():
    import subprocess
    import sys

    code = ("import sys; import stepper.brightsky.executor; "
            "print('stepper.main' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[3]), check=True)
    assert out.stdout.strip() == "False"
