"""
brightsky-verify acceptance: the "Heal and propose" story and the engine
changes it names.

Source: spec.md, story "Heal and propose" (whose second paragraph is the recipe
these tests follow: `verify_slug` or the CLI over a stubbed `Transport`, an
`executor.EngineExecutor(page, resolver, ai_service=...)`, and the two page
probes `DOMSnapshotCascade.capture` and `VisualBridge.check` monkeypatched),
the Edge cases table, Design § Decisions and Interfaces § Engine changes.
"""
from __future__ import annotations

import inspect

import pytest

from bs_harness import (
    HEALED_LINK,
    SLUG,
    FakeAI,
    FakePage,
    FakeResolver,
    Probe,
    Rule,
    engine_world,
    has,
    is_hobbit_link,
    is_step,
    make_client,
    patch_probes,
    pilot_backend,
    pilot_steps,
    run_cli,
    run_report,
    steps_by_number,
    versions_path,
    workflow_detail,
)


def _healed_link_for_step_2(step):
    return {"css": HEALED_LINK} if is_step(2)(step) else None


def _missing_cfg_for_step_2(step):
    return {"css": "#embed-direct-guess"} if is_step(2)(step) else None


async def _verify(world, backend=None, **kw):
    from stepper.brightsky.verify import verify_slug

    backend = backend if backend is not None else pilot_backend()
    outcome = await verify_slug(make_client(backend), world.executor, SLUG, **kw)
    return outcome, backend


def _proposal(backend):
    sent = backend.sent("POST", versions_path())
    assert len(sent) == 1, f"expected exactly one proposal, got {len(sent)}"
    return sent[0].body


# Story: Every acting step `map_version` returns (`click`, `fill`) has
#        `extra["strict"] is True`. Through `EngineExecutor`, the resolver double
#        is asked for the stored target with `strict=True`, so the
#        description-driven fallbacks never stand in for it, and a miss on that
#        target is what starts the heal loop.
async def test_the_stored_target_is_looked_up_strictly_and_its_miss_starts_the_heal(
        monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), direct=_healed_link_for_step_2)

    await _verify(world)

    stored = [c for c in world.resolver.calls if is_hobbit_link(c["cfg"])]
    assert stored, "the resolver was never asked for the stored target"
    assert all(c["strict"] is True for c in stored)
    assert any(is_step(2)(call["step"]) for call in world.probe.calls)


# Story: Heal order per step ...:
#  - the probe gives an `embed_direct` cfg that resolves: no AI call, tier `embed_direct`;
async def test_an_embed_direct_cfg_that_resolves_heals_with_no_ai_call(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), direct=_healed_link_for_step_2)

    outcome, backend = await _verify(world)

    assert world.ai.task_types == []
    step = steps_by_number(run_report(backend))[2]
    assert step["tier"] == "embed_direct"
    assert outcome.status == "healed"


#  - the probe gives no cfg: `["heal"]` and tier `cheap` when that reply resolves;
async def test_no_cfg_asks_the_cheap_tier_once_when_its_reply_resolves(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), ai_elements=[{"css": HEALED_LINK}])

    outcome, backend = await _verify(world)

    assert world.ai.task_types == ["heal"]
    assert steps_by_number(run_report(backend))[2]["tier"] == "cheap"
    assert outcome.status == "healed"


#  - the probe gives an `embed_direct` cfg that misses, and every AI reply
#    misses: exactly `["heal", "heal", "heal_big"]`. The failed `embed_direct`
#    try does not count as one of the two cheap tries ...
async def test_an_embed_direct_miss_is_free_then_two_cheap_tries_then_the_big_model(
        monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), direct=_missing_cfg_for_step_2)

    outcome, backend = await _verify(world)

    assert world.ai.task_types == ["heal", "heal", "heal_big"]
    report = run_report(backend)
    assert report["result"] == "failed"
    assert steps_by_number(report)[2]["outcome"] == "failed"
    assert backend.sent("POST", versions_path()) == []
    assert outcome.status == "failed"


#  - the same with a third reply that resolves: tier `big`;
async def test_a_third_reply_that_resolves_heals_on_the_big_tier(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), direct=_missing_cfg_for_step_2,
                         ai_elements=[{"css": "#miss-1"}, {"css": "#miss-2"},
                                      {"css": HEALED_LINK}])

    outcome, backend = await _verify(world)

    assert world.ai.task_types == ["heal", "heal", "heal_big"]
    assert steps_by_number(run_report(backend))[2]["tier"] == "big"
    assert outcome.status == "healed"


#  - after the `embed_direct` miss, the probe is asked with `skip_direct=True`,
#    and every `heal` and `heal_big` prompt the AI double records contains the
#    content of the payload it returned for that call (the page, not an empty `dom`).
async def test_after_an_embed_direct_miss_the_ai_sees_the_page(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), direct=_missing_cfg_for_step_2)

    await _verify(world)

    step2_probes = [c for c in world.probe.calls if is_step(2)(c["step"])]
    assert step2_probes and step2_probes[0]["skip_direct"] is False
    assert all(c["skip_direct"] is True for c in step2_probes[1:])
    assert len(step2_probes) >= 2

    latest_payload = None
    ai_calls = 0
    for event in world.events:
        if event[0] == "capture":
            latest_payload = event[3]
        elif event[0] == "ai":
            ai_calls += 1
            assert latest_payload is not None
            assert latest_payload.content, "the AI was given an empty dom"
            assert latest_payload.content in event[2]
    assert ai_calls == 3


# Story: The strict order is the BrightSky executors' only. `StepRunner` and
#        `RunConfig` default to `strict_heal_order=False`, and with the default a
#        `run --heal N` heals exactly as before: an `embed_direct` cfg is retried
#        on every attempt with no AI call, the probe is never asked with
#        `skip_direct`, and `heal_big` is never asked for.
def _runner(page, resolver, ai, **kw):
    from stepper.engine.actions.factory import build_default_registry
    from stepper.engine.healer.ai_healer import AiHealer
    from stepper.engine.planner.schema_extractor import ActionSchemaExtractor
    from stepper.engine.runner.step_runner import StepRunner
    from unittest.mock import MagicMock

    registry = build_default_registry()
    healer = AiHealer(ActionSchemaExtractor.extract(registry), ai_service=ai)
    return StepRunner(page=page, action_factory=registry, resolver=resolver,
                      reporter=MagicMock(), healer=healer, max_heal_attempts=3, **kw)


def _broken_click():
    from stepper.engine.interfaces import StepConfig

    return StepConfig(action="click", description="Open the book page",
                      element={"role": "link", "name": "The Hobbit"},
                      extra={"strict": True})


def test_strict_heal_order_defaults_to_false_on_step_runner_and_run_config():
    from stepper.engine.runner.step_runner import StepRunner
    from stepper.main import RunConfig

    parameter = inspect.signature(StepRunner.__init__).parameters.get("strict_heal_order")
    assert parameter is not None, "StepRunner has no strict_heal_order parameter"
    assert parameter.default is False
    assert RunConfig(task="x").strict_heal_order is False


async def test_by_default_the_heal_loop_behaves_as_before(monkeypatch):
    from stepper.engine.runner.step_runner import StepRunner

    # The opt-in exists (and is off) — otherwise this would only describe today.
    assert inspect.signature(StepRunner.__init__).parameters["strict_heal_order"].default \
        is False

    events: list = []
    page = FakePage("https://openlibrary.org/search?q=The+Hobbit")
    resolver = FakeResolver(page, [])
    probe = Probe(events, direct=lambda step: {"css": "#embed-direct-guess"})
    patch_probes(monkeypatch, probe)
    ai = FakeAI(events)

    results, _ = await _runner(page, resolver, ai).run([_broken_click()])

    assert results[0].status in ("failed", "skipped")
    assert ai.task_types == []
    assert len(probe.calls) == 3
    assert all(c["skip_direct"] is False for c in probe.calls)


# Interfaces § Engine changes: `StepRunner(..., strict_heal_order: bool = False)`
#        ... Only when it is true does `StepRunner._run_heal_loop` pass `tried=`,
#        record `healed_element["tier"]`, call `capture(..., skip_direct=True)` once
#        `embed_direct` has been tried, and leave the first `FREE_TIER` try out of
#        `max_heal_attempts`.
async def test_strict_heal_order_on_a_step_runner_is_free_try_then_cheap_cheap_big(
        monkeypatch):
    events: list = []
    page = FakePage("https://openlibrary.org/search?q=The+Hobbit")
    resolver = FakeResolver(page, [Rule("healed", lambda c: has(c, HEALED_LINK),
                                        click_to="https://openlibrary.org/works/OL1W")])
    probe = Probe(events, direct=lambda step: {"css": "#embed-direct-guess"})
    patch_probes(monkeypatch, probe)
    ai = FakeAI(events, [{"css": "#miss-1"}, {"css": "#miss-2"}, {"css": HEALED_LINK}])

    results, _ = await _runner(page, resolver, ai, strict_heal_order=True).run(
        [_broken_click()])

    assert ai.task_types == ["heal", "heal", "heal_big"]
    assert results[0].status == "healed"
    assert results[0].healed_element["tier"] == "big"
    assert [c["skip_direct"] for c in probe.calls][0] is False
    assert all(c["skip_direct"] is True for c in probe.calls[1:])


# Interfaces § Engine changes: `AiHealer.tier_for(dom, tried)`: `"embed_direct"`
#        when `dom.healed_cfg` is set and `"embed_direct"` is not in `tried`; else
#        `"big"` when `tried` holds two `"cheap"`; else `"cheap"`.
#        `stepper.engine.healer.interfaces.FREE_TIER = "embed_direct"`.
def test_ai_healer_names_the_next_rung():
    from stepper.engine.healer.ai_healer import AiHealer
    from stepper.engine.healer.interfaces import FREE_TIER, DomPayload

    healer = AiHealer({"click": {"description": "Click."}}, ai_service=FakeAI([]))
    direct = DomPayload(strategy_used="embed_direct", content="", healed_cfg={"css": "#x"})
    page = DomPayload(strategy_used="embed_candidates", content="{}", healed_cfg=None)

    assert FREE_TIER == "embed_direct"
    assert healer.tier_for(direct, ()) == "embed_direct"
    assert healer.tier_for(direct, ("embed_direct",)) == "cheap"
    assert healer.tier_for(page, ()) == "cheap"
    assert healer.tier_for(page, ("embed_direct", "cheap")) == "cheap"
    assert healer.tier_for(page, ("embed_direct", "cheap", "cheap")) == "big"


# Interfaces § Engine changes: a non-abstract `HealerStrategy.tier_for(dom, tried)
#        -> str` (default `"healer"`).
def test_a_healer_without_its_own_tier_for_is_named_healer():
    from stepper.engine.healer.interfaces import DomPayload, HealerStrategy

    class _Minimal(HealerStrategy):
        async def heal(self, step, error, dom, **kw):
            return [step]

    assert _Minimal().tier_for(DomPayload("aria", "{}"), ()) == "healer"


# Interfaces § Engine changes: `StepRunner.add_hook(domain: str | None, hook:
#        StepHook) -> StepRunner`.
async def test_add_hook_attaches_a_hook_for_its_domain_and_returns_the_runner():
    from stepper.engine.actions.factory import build_default_registry
    from stepper.engine.interfaces import StepConfig
    from stepper.engine.runner.hooks import StepHook
    from stepper.engine.runner.step_runner import StepRunner
    from unittest.mock import MagicMock

    seen: list = []

    class _Hook(StepHook):
        async def after(self, session, step, result, idx):
            seen.append((step.action, result.status))

    page = FakePage()
    runner = StepRunner(page=page, action_factory=build_default_registry(),
                        reporter=MagicMock())
    assert runner.add_hook("web", _Hook()) is runner

    await runner.run([StepConfig(action="navigate", url="https://openlibrary.org/")])

    assert seen == [("navigate", "passed")]


# Story: When the heal succeeds and every other step passes, the run is reported
#        first, with `result: "failed"`. The healed step has `outcome: "failed"`,
#        `matched: false` and `tier` naming the rung. The CLI prints `<slug> v<N>
#        healed -> proposed v<M>` and exits 1.
def test_a_healed_run_is_reported_failed_first_then_proposed(monkeypatch, capsys):
    backend = pilot_backend(proposed=2)
    world = engine_world(monkeypatch, broken=(2,), direct=_healed_link_for_step_2)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    assert f"{SLUG} v1 healed -> proposed v2" in result.lines
    posts = [r.path for r in backend.requests if r.method == "POST"]
    assert posts == [f"/api/workflows/{SLUG}/runs", versions_path()]
    report = run_report(backend)
    assert report["result"] == "failed"
    healed = steps_by_number(report)[2]
    assert healed["outcome"] == "failed"
    assert healed["matched"] is False
    assert healed["tier"] == "embed_direct"
    others = steps_by_number(report)
    assert others[1]["outcome"] == "passed" and others[3]["outcome"] == "passed"


# Story: A healed step is never reported as passed in the same run.
async def test_a_healed_step_is_never_reported_passed(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), ai_elements=[{"css": HEALED_LINK}])

    outcome, backend = await _verify(world)

    report = run_report(backend)
    assert report["result"] != "passed"
    assert steps_by_number(report)[2]["outcome"] != "passed"
    assert outcome.status == "healed"


# Story: After that report, exactly one `POST /api/workflows/<slug>/versions` is
#        sent. It carries the fetched version's steps with only the healed steps'
#        `target` replaced, `source: "stepper"` when every heal was
#        `embed_direct`, `source: "haiku"` when any heal used an AI rung, and a
#        `note` naming the run's idempotency key, the version it ran and, for each
#        healed step, its number and its old and new target.
async def test_an_embed_direct_heal_is_proposed_from_stepper(monkeypatch):
    backend = pilot_backend(version=7, proposed=8)
    world = engine_world(monkeypatch, broken=(2,), direct=_healed_link_for_step_2)

    outcome, backend = await _verify(world, backend)

    proposal = _proposal(backend)
    fetched = pilot_steps()
    assert proposal["source"] == "stepper"
    assert len(proposal["steps"]) == 3
    assert proposal["steps"][0] == fetched[0]
    assert proposal["steps"][2] == fetched[2]
    healed = proposal["steps"][1]
    assert {k: v for k, v in healed.items() if k != "target"} == \
        {k: v for k, v in fetched[1].items() if k != "target"}
    assert healed["target"] != fetched[1]["target"]
    assert HEALED_LINK in healed["target"]["selectors"]

    note = proposal["note"]
    key = run_report(backend)["idempotencyKey"]
    assert key in note
    assert "7" in note
    assert "2" in note
    assert "The Hobbit" in note
    assert HEALED_LINK in note
    assert outcome.status == "healed"
    assert outcome.proposed_version == 8


async def test_an_ai_heal_is_proposed_from_haiku(monkeypatch):
    world = engine_world(monkeypatch, broken=(2,), ai_elements=[{"css": HEALED_LINK}])

    _, backend = await _verify(world)

    proposal = _proposal(backend)
    assert proposal["source"] == "haiku"
    assert HEALED_LINK in proposal["steps"][1]["target"]["selectors"]


# Story: A proposed step keeps its action. A text-entry step (target role
#        `textbox`, an `url_change` outcome) healed to a role-less element such as
#        `{"placeholder": "Search"}` is proposed with the original `role` (and no
#        accessibleName) beside the new selector, so `map_version` on the
#        proposed steps maps it to a `fill` of the same value, not a `click`,
#        whose element cfg is the healed selector alone.
async def test_a_healed_text_entry_step_is_proposed_so_it_still_maps_to_a_fill(monkeypatch):
    from stepper.brightsky.mapping import map_version

    world = engine_world(monkeypatch, broken=(1,),
                         direct=lambda s: {"placeholder": "Search"} if is_step(1)(s) else None)

    _, backend = await _verify(world)

    proposal = _proposal(backend)
    target = proposal["steps"][0]["target"]
    assert target["role"] == "textbox"
    assert not target.get("accessibleName")
    assert target["selectors"]

    mapped = map_version(workflow_detail(proposal["steps"]))
    fills = [s for s in mapped.steps if mapped.step_numbers.get(s.description) == 1
             and s.action in ("click", "fill")]
    assert len(fills) == 1
    assert fills[0].action == "fill"
    assert fills[0].input_value == "The Hobbit"
    assert "role" not in fills[0].element and len(fills[0].element) == 1


# Story: When a heal succeeded but another step failed, the run is reported
#        failed and nothing is proposed.
async def test_a_heal_with_another_step_failing_proposes_nothing(monkeypatch):
    world = engine_world(monkeypatch, broken=(2, 3), direct=_healed_link_for_step_2)

    outcome, backend = await _verify(world)

    report = run_report(backend)
    assert report["result"] == "failed"
    steps = steps_by_number(report)
    assert steps[2]["outcome"] == "failed"
    assert steps[3]["outcome"] == "failed"
    assert backend.sent("POST", versions_path()) == []
    assert outcome.status == "failed"


# Story: With no AI key in the environment (an `EngineExecutor` built without an
#        `ai_service`, so it uses a real `AIService`), only `embed_direct` can
#        heal. A step the probe gives no cfg for stays `failed` in the run
#        payload, nothing is proposed, and the CLI exits 1.
def _forbid_provider_requests(monkeypatch):
    from stepper.engine.ai import providers

    async def _refuse(self, *a, **kw):
        raise AssertionError(f"{type(self).__name__} made a request")

    for cls in (providers.GroqProvider, providers.GeminiProvider, providers.ClaudeProvider):
        monkeypatch.setattr(cls, "chat", _refuse)


def test_with_no_ai_key_a_step_the_probe_cannot_fix_stays_failed(monkeypatch, capsys):
    _forbid_provider_requests(monkeypatch)
    backend = pilot_backend()
    world = engine_world(monkeypatch, broken=(2,), with_ai=False)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    report = run_report(backend)
    assert report["result"] == "failed"
    assert steps_by_number(report)[2]["outcome"] == "failed"
    assert backend.sent("POST", versions_path()) == []


def test_with_no_ai_key_embed_direct_still_heals(monkeypatch, capsys):
    _forbid_provider_requests(monkeypatch)
    backend = pilot_backend(proposed=2)
    world = engine_world(monkeypatch, broken=(2,), with_ai=False,
                         direct=_healed_link_for_step_2)

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    assert f"{SLUG} v1 healed -> proposed v2" in result.lines
    assert _proposal(backend)["source"] == "stepper"


# Story: `AIService().chat(..., task_type="heal_big")` with `ANTHROPIC_API_KEY`
#        unset raises `RuntimeError` and makes no request.
async def test_heal_big_without_an_anthropic_key_raises_and_makes_no_request(monkeypatch):
    from stepper.engine.ai import providers
    from stepper.engine.ai.service import AIService

    asked: list = []

    async def _record(self, *a, **kw):
        asked.append(type(self).__name__)
        return "[]"

    for cls in (providers.GroqProvider, providers.GeminiProvider, providers.ClaudeProvider):
        monkeypatch.setattr(cls, "chat", _record)
    # The cheap providers are configured: heal_big must still not reach them.
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.setenv("GEMINI_API_KEY", "gem_fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        await AIService().chat("heal this", task_type="heal_big", system="s")

    assert asked == []


# Design § Big model id: the constant `_BIG_MODEL = "claude-sonnet-5-5"`.
# Interfaces: `AIService` gets the task type `heal_big` (chain `["claude_big"]`,
#        max tokens 1024). `ClaudeProvider(model=...)` defaults to today's Haiku id.
# Migration: The `heal` task chain ... unchanged.
async def test_heal_big_asks_the_big_claude_model_and_heal_still_asks_haiku(monkeypatch):
    import anthropic

    from stepper.engine.ai import providers
    from stepper.engine.ai.service import AIService

    created: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            created.append(kwargs)

            class _Text:
                text = "[]"

            class _Reply:
                content = [_Text()]

            return _Reply()

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    groq_asked: list = []

    async def _groq(self, *a, **kw):
        groq_asked.append(1)
        return "[]"

    monkeypatch.setattr(anthropic, "Anthropic", _Anthropic)
    monkeypatch.setattr(providers.GroqProvider, "chat", _groq)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")

    await AIService().chat("heal this", task_type="heal_big", system="s")

    assert groq_asked == []
    assert len(created) == 1
    assert created[0]["model"] == "claude-sonnet-5-5"
    assert created[0]["max_tokens"] == 1024

    monkeypatch.delenv("GROQ_API_KEY")
    await AIService().chat("heal this", task_type="heal", system="s")
    assert created[1]["model"] == "claude-haiku-4-5-20251001"

    assert providers.ClaudeProvider(model="claude-sonnet-5-5").is_configured is True


# Edge: `ANTHROPIC_API_KEY` unset | the big-model rung raises inside the heal
#       loop, and a step the cheap tier could not fix stays failed
async def test_without_anthropic_the_big_rung_raises_and_the_step_stays_failed(monkeypatch):
    from stepper.engine.ai import providers

    events: list = []
    groq_prompts: list = []

    async def _groq(self, prompt, system="", max_tokens=512):
        from bs_harness import last_captured_step, reply_for

        groq_prompts.append(prompt)
        return reply_for(last_captured_step(events), {"css": f"#miss-{len(groq_prompts)}"})

    async def _refuse(self, *a, **kw):
        raise AssertionError(f"{type(self).__name__} made a request")

    monkeypatch.setattr(providers.GroqProvider, "chat", _groq)
    monkeypatch.setattr(providers.GeminiProvider, "chat", _refuse)
    monkeypatch.setattr(providers.ClaudeProvider, "chat", _refuse)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")

    world = engine_world(monkeypatch, broken=(2,), with_ai=False)
    world.probe.events = events  # the Groq double copies the step the loop probed
    outcome, backend = await _verify(world)

    assert len(groq_prompts) == 2
    report = run_report(backend)
    assert steps_by_number(report)[2]["outcome"] == "failed"
    assert backend.sent("POST", versions_path()) == []
    assert outcome.status == "failed"


# Edge: A step's outcome is not met (for example, the URL never contains
#       `/search`) | the step is failed with `expected outcome not met: ...`,
#       `matched: true`
async def test_an_outcome_that_is_not_met_fails_the_step_as_matched(monkeypatch):
    from stepper.brightsky.mapping import map_version

    world = engine_world(monkeypatch, enter_to=None)

    executed = await world.executor.execute(map_version(workflow_detail()), headless=True)

    assert [e.step_number for e in executed] == [1, 2, 3]
    first = executed[0]
    assert first.outcome == "failed"
    assert first.matched is True
    assert "expected outcome not met" in (first.error or "")
    assert [e.outcome for e in executed[1:]] == ["unchecked", "unchecked"]


# Edge: The page is not on the step's `expectedUrl` before it acts | the step is
#       failed before it acts, `matched: false`
async def test_a_step_off_its_expected_url_fails_before_it_acts(monkeypatch):
    from stepper.brightsky.mapping import map_version

    steps = pilot_steps()
    steps[0]["expectedOutcome"] = {"kind": "url_change"}
    world = engine_world(monkeypatch, enter_to="https://openlibrary.org/elsewhere?q=x")

    executed = await world.executor.execute(map_version(workflow_detail(steps)),
                                            headless=True)

    assert executed[0].outcome == "passed"
    second = executed[1]
    assert second.outcome == "failed"
    assert second.matched is False
    assert ("click", "hobbit link") not in world.page.events


# Interfaces: `executor.ExecutedStep(step_number, outcome, matched, tier, healed,
#        healed_element, error)`. `healed` is true for a step StepRunner reported
#        `healed`; its `outcome` is still `failed`.
async def test_engine_executor_reports_a_heal_as_a_failed_outcome(monkeypatch):
    from stepper.brightsky.mapping import map_version

    world = engine_world(monkeypatch, broken=(2,), direct=_healed_link_for_step_2)

    executed = await world.executor.execute(map_version(workflow_detail()), headless=True)

    assert [e.outcome for e in executed] == ["passed", "failed", "passed"]
    assert executed[1].healed is True
    assert executed[1].matched is False
    assert executed[1].tier == "embed_direct"
    assert executed[0].healed is False and executed[0].matched is True and executed[0].tier


# Edge: A heal whose new element has no role+name, no css, no xpath and no id
#       (only text) | the run is reported failed; nothing is proposed; the CLI
#       says the store cannot describe the healed element
def test_a_heal_the_store_cannot_describe_is_reported_failed_and_not_proposed(
        monkeypatch, capsys):
    backend = pilot_backend()
    world = engine_world(monkeypatch, broken=(2,), ai_elements=[{"text": "The Hobbit"}])

    result = run_cli(monkeypatch, capsys, ["brightsky", "verify", SLUG],
                     backend=backend, executor=world.executor)

    assert result.code == 1
    assert run_report(backend)["result"] == "failed"
    assert backend.sent("POST", versions_path()) == []
    assert "describe" in (result.out + result.err).lower()


# Edge: A step healed by scroll/wait injection, so its element did not change |
#       the run is reported failed; nothing is proposed
@pytest.mark.parametrize("visual", ["hidden", "disabled"])
async def test_a_heal_by_injection_is_reported_failed_and_not_proposed(monkeypatch, visual):
    from bs_harness import pilot_rules

    rules = pilot_rules()
    for rule in rules:
        if rule.name == "hobbit link":
            rule.misses = 1   # missed once, then found once the page has settled
    world = engine_world(monkeypatch, rules=rules, visual=visual)

    outcome, backend = await _verify(world)

    report = run_report(backend)
    assert report["result"] == "failed"
    assert steps_by_number(report)[2]["outcome"] == "failed"
    assert backend.sent("POST", versions_path()) == []
    assert outcome.proposed_version is None
