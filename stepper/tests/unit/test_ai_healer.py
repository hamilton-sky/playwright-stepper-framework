"""
AiHealer — what reaches the network, and what it is allowed to hand back.

Two things matter here and neither had a test.

The first is the zero-token claim: when DOMSnapshotCascade resolved the element
outright, AiHealer must synthesise the replacement from the payload and never
call a provider. A regression there is invisible — healing still works, the run
still passes, it just costs money on every heal. The AIService double below
raises if it is called at all, so that path is asserted rather than assumed.

The second is that an LLM's reply is untrusted input. It arrives as text, it is
often not JSON, and when it is JSON it may name an action that does not exist.
Anything that gets past _parse becomes a step the runner executes.
"""
from __future__ import annotations

import json
from typing import cast

import pytest

from stepper.engine.ai.service import AIService
from stepper.engine.healer.ai_healer import AiHealer
from stepper.engine.healer.interfaces import DomPayload, HealingError
from stepper.engine.interfaces import StepConfig


# ── Doubles ───────────────────────────────────────────────────────────────────

class _RecordingAI:
    """An AIService stand-in that records its calls and replies with a script."""

    def __init__(self, reply: str = "[]"):
        self.reply = reply
        self.calls: list[dict] = []

    async def chat(self, prompt: str, task_type: str = "classify", system: str = "") -> str:
        self.calls.append({"prompt": prompt, "task_type": task_type, "system": system})
        return self.reply


class _ForbiddenAI:
    """Fails the test if anything calls a provider."""

    async def chat(self, *a, **kw) -> str:
        raise AssertionError(
            "AiHealer called the AI — this path is supposed to cost zero tokens"
        )


_SCHEMA = {
    "click":    {"description": "Click an element."},
    "fill":     {"description": "Fill an input."},
    "navigate": {"description": "Go to a URL."},
}


def _healer(ai=None) -> AiHealer:
    # AiHealer's type hint names AIService, but the only thing it ever asks of
    # it is `await .chat(prompt, task_type=..., system=...)`. Substituting a
    # double here is the Strategy pattern working, not a hole in the typing —
    # cast keeps a checker quiet without pretending the double is the real class.
    return AiHealer(action_schema=_SCHEMA, ai_service=cast(AIService, ai or _RecordingAI()))


def _failed_step(**kw) -> StepConfig:
    base = {
        "action": "fill",
        "description": "fill the username field",
        "element": {"css": ".broken-selector"},
        "input_value": "standard_user",
        "extra": {"timeout": 5000},
        "retry": 2,
        "continue_on_failure": True,
    }
    base.update(kw)
    return StepConfig(**base)


# ── The zero-token fast path ──────────────────────────────────────────────────

async def test_a_resolved_payload_heals_without_calling_the_ai():
    """The whole point of embed_direct: no provider is touched."""
    healer = _healer(_ForbiddenAI())
    dom = DomPayload(
        strategy_used="embed_direct",
        content="",
        healed_cfg={"placeholder": "Username"},
        token_estimate=0,
    )

    steps = await healer.heal(_failed_step(), "timeout", dom)

    assert len(steps) == 1
    assert steps[0].element == {"placeholder": "Username"}


async def test_the_fast_path_changes_the_selector_and_nothing_else():
    """
    Only `element` was wrong. A heal that also dropped the retry budget or the
    continue_on_failure flag would silently change how the step behaves on its
    next failure — the selector is the bug, not the step's policy.
    """
    healer = _healer(_ForbiddenAI())
    original = _failed_step()
    dom = DomPayload("embed_direct", "", {"placeholder": "Username"}, 0)

    healed = (await healer.heal(original, "timeout", dom))[0]

    assert healed.element != original.element
    for field in ("action", "description", "url", "input_value", "wait_for",
                  "extra", "when", "retry", "retry_delay_ms",
                  "continue_on_failure", "skip_screenshot"):
        assert getattr(healed, field) == getattr(original, field), field


async def test_an_unresolved_payload_does_call_the_ai():
    """The counterpart: without a healed_cfg there is nothing to do locally."""
    ai = _RecordingAI(json.dumps([{
        "action": "fill", "element": {"placeholder": "Username"},
        "input_value": "standard_user", "description": "fill the username field",
    }]))
    dom = DomPayload("scoped", '{"best_match": {}}', None, 120)

    steps = await _healer(ai).heal(_failed_step(), "timeout", dom)

    assert len(ai.calls) == 1
    assert ai.calls[0]["task_type"] == "heal", "must use the cheap provider chain"
    assert steps[0].element == {"placeholder": "Username"}


# ── What goes into the prompt ─────────────────────────────────────────────────

async def test_the_prompt_carries_the_failure_and_the_dom():
    ai = _RecordingAI('[{"action": "click", "element": {"text": "Go"}}]')
    dom = DomPayload("scoped", '{"best_match": {"text": "Go"}}', None, 90)

    await _healer(ai).heal(_failed_step(), "Timeout 5000ms exceeded", dom)

    payload = json.loads(ai.calls[0]["prompt"])
    assert payload["failed_step"]["action"] == "fill"
    assert payload["failed_step"]["element"] == {"css": ".broken-selector"}
    assert payload["error"] == "Timeout 5000ms exceeded"
    assert payload["dom"] == dom.content


async def test_the_system_prompt_lists_only_registered_actions():
    """
    The schema is injected so the model cannot invent an action name. A stale
    hardcoded list here is how a healer starts proposing steps the registry has
    never heard of.
    """
    ai = _RecordingAI('[{"action": "click", "element": {"text": "Go"}}]')

    await _healer(ai).heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))

    system = ai.calls[0]["system"]
    for action in _SCHEMA:
        assert action in system
    assert "paginate" not in system, "only the schema it was constructed with"


async def test_nearby_steps_are_included_when_the_caller_knows_the_position():
    """
    Which page the run is on narrows what the element could be. The window is
    deliberately small — the whole workflow would be most of the prompt budget.
    """
    ai = _RecordingAI('[{"action": "click", "element": {"text": "Go"}}]')
    all_steps = [StepConfig(action="click", description=f"step {i}") for i in range(20)]

    await _healer(ai).heal(
        _failed_step(), "err", DomPayload("scoped", "{}", None, 10),
        all_steps=all_steps, current_index=10, context_vars={"count": 3},
    )

    ctx = json.loads(ai.calls[0]["prompt"])["workflow_context"]
    assert ctx["current_index"] == 10
    assert ctx["total_steps"] == 20
    assert ctx["context_vars"] == {"count": 3}
    assert len(ctx["nearby_steps"]) == 7, "3 before, the step itself, 3 after"
    assert ctx["nearby_steps"][0]["description"] == "step 7"
    assert ctx["nearby_steps"][-1]["description"] == "step 13"


async def test_the_window_does_not_run_off_the_front_of_the_workflow():
    """Failing on step 1 must not produce a negative slice."""
    ai = _RecordingAI('[{"action": "click", "element": {"text": "Go"}}]')
    all_steps = [StepConfig(action="click", description=f"step {i}") for i in range(5)]

    await _healer(ai).heal(
        _failed_step(), "err", DomPayload("scoped", "{}", None, 10),
        all_steps=all_steps, current_index=0,
    )

    nearby = json.loads(ai.calls[0]["prompt"])["workflow_context"]["nearby_steps"]
    assert nearby[0]["description"] == "step 0"
    assert len(nearby) == 4


async def test_no_workflow_context_when_the_caller_gives_no_position():
    ai = _RecordingAI('[{"action": "click", "element": {"text": "Go"}}]')

    await _healer(ai).heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))

    assert "workflow_context" not in json.loads(ai.calls[0]["prompt"])


# ── The reply is untrusted ────────────────────────────────────────────────────

async def test_a_reply_that_is_not_json_is_rejected():
    healer = _healer(_RecordingAI("I'd suggest using the placeholder selector!"))

    with pytest.raises(HealingError, match="invalid JSON"):
        await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))


async def test_a_bare_object_is_accepted_as_a_one_step_list():
    """Models drop the outer array constantly. Tolerating it is not a soundness hole."""
    healer = _healer(_RecordingAI(json.dumps(
        {"action": "click", "element": {"text": "Log in"}, "description": "click log in"}
    )))

    steps = await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))

    assert len(steps) == 1
    assert steps[0].action == "click"


@pytest.mark.parametrize("reply", ["[]", "null", '""'])
async def test_an_empty_reply_is_rejected(reply):
    """No replacement is a failed heal, not a heal that removes the step."""
    healer = _healer(_RecordingAI(reply))

    with pytest.raises(HealingError):
        await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))


async def test_an_unregistered_action_is_rejected():
    """
    The single most important check in the module: whatever comes back becomes a
    step the runner executes. An action the registry has never heard of must die
    here, with the known set named, rather than at dispatch time.
    """
    healer = _healer(_RecordingAI(json.dumps(
        [{"action": "delete_everything", "element": {"css": "body"}}]
    )))

    with pytest.raises(HealingError, match="unknown action 'delete_everything'"):
        await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))


async def test_one_bad_step_rejects_the_whole_reply():
    """A partially-applied heal is worse than none — it runs half a plan."""
    healer = _healer(_RecordingAI(json.dumps([
        {"action": "click", "element": {"text": "OK"}},
        {"action": "not_an_action", "element": {"text": "??"}},
    ])))

    with pytest.raises(HealingError, match="unknown action"):
        await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))


async def test_a_non_dict_step_in_the_list_is_rejected():
    healer = _healer(_RecordingAI(json.dumps([["click", ".btn"]])))

    with pytest.raises(HealingError, match="not a dict"):
        await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))


async def test_a_valid_multi_step_reply_is_accepted():
    """Some heals genuinely need two steps — open the menu, then click the item."""
    healer = _healer(_RecordingAI(json.dumps([
        {"action": "click", "element": {"role": "button", "name": "Menu"},
         "description": "open the menu"},
        {"action": "click", "element": {"text": "Settings"},
         "description": "click settings"},
    ])))

    steps = await healer.heal(_failed_step(), "err", DomPayload("scoped", "{}", None, 10))

    assert [s.action for s in steps] == ["click", "click"]
    assert steps[0].element == {"role": "button", "name": "Menu"}
