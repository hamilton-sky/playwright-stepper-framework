"""
AIService — the provider chain, and the order it spends money in.

The framework's cost story is that healing and classification try Groq first,
Gemini second, and Claude last, and that planning goes straight to Claude
because the cheap models cannot do it. That ordering is the entire reason the
abstraction exists, and it was only ever asserted in a docstring.

Providers are replaced wholesale here. Nothing in this module should reach a
network, and the test that nothing does is the one below that counts calls.
"""
from __future__ import annotations

import pytest

from stepper.engine.ai.service import AIService, _MAX_TOKENS, _TASK_CHAINS


class _Provider:
    """A provider double: configured or not, working or not, and it counts calls."""

    def __init__(self, name: str, *, configured: bool = True, fails: bool = False):
        self.name = name
        self._configured = configured
        self._fails = fails
        self.calls: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def chat(self, prompt: str, system: str = "", max_tokens: int = 512) -> str:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        if self._fails:
            raise RuntimeError(f"{self.name} is down")
        return f"answered by {self.name}"


def _service(**providers) -> tuple[AIService, dict[str, _Provider]]:
    """An AIService with every provider swapped for a double."""
    doubles = {
        name: providers.get(name) or _Provider(name)
        for name in ("groq", "gemini", "claude")
    }
    service = AIService()
    service._providers = doubles          # type: ignore[assignment]
    return service, doubles


# ── Cheapest first ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("task_type", ["classify", "heal"])
async def test_the_cheapest_provider_answers_and_the_rest_are_never_asked(task_type):
    service, p = _service()

    result = await service.chat("hello", task_type=task_type)

    assert result == "answered by groq"
    assert len(p["groq"].calls) == 1
    assert p["gemini"].calls == [], "gemini was asked despite groq answering"
    assert p["claude"].calls == [], "claude was asked despite groq answering"


async def test_an_unconfigured_provider_is_skipped_not_attempted():
    """
    No key is not an error — it is the normal state for two of three providers
    on most installs. Skipping must be silent and must not consume the attempt.
    """
    service, p = _service(groq=_Provider("groq", configured=False))

    result = await service.chat("hello", task_type="heal")

    assert result == "answered by gemini"
    assert p["groq"].calls == []


async def test_a_failing_provider_falls_through_to_the_next():
    service, p = _service(groq=_Provider("groq", fails=True))

    result = await service.chat("hello", task_type="heal")

    assert result == "answered by gemini"
    assert len(p["groq"].calls) == 1, "groq should have been tried before falling through"


async def test_the_chain_walks_all_the_way_down():
    service, p = _service(
        groq=_Provider("groq", fails=True),
        gemini=_Provider("gemini", configured=False),
    )

    result = await service.chat("hello", task_type="heal")

    assert result == "answered by claude"


async def test_every_provider_failing_raises_rather_than_returning_nothing():
    """
    A heal with no provider must raise. Returning "" would send an empty reply
    into AiHealer._parse, which would report it as malformed JSON — the wrong
    error, pointing at the wrong component.
    """
    service, _ = _service(
        groq=_Provider("groq", fails=True),
        gemini=_Provider("gemini", fails=True),
        claude=_Provider("claude", fails=True),
    )

    with pytest.raises(RuntimeError, match="all providers failed"):
        await service.chat("hello", task_type="heal")


async def test_no_provider_configured_at_all_raises():
    """The common first-run state: nothing in .env. It must say so plainly."""
    service, _ = _service(
        groq=_Provider("groq", configured=False),
        gemini=_Provider("gemini", configured=False),
        claude=_Provider("claude", configured=False),
    )

    with pytest.raises(RuntimeError, match="all providers failed"):
        await service.chat("hello", task_type="heal")


# ── Planning is different ─────────────────────────────────────────────────────

async def test_planning_goes_straight_to_claude():
    """
    Planning is the one task the cheap models are not trusted with. Quietly
    adding groq to this chain would save pennies and produce unrunnable plans.
    """
    service, p = _service()

    result = await service.chat("plan this", task_type="plan")

    assert result == "answered by claude"
    assert p["groq"].calls == []
    assert p["gemini"].calls == []


async def test_a_failing_claude_on_a_plan_does_not_fall_back_to_a_cheap_model():
    service, p = _service(claude=_Provider("claude", fails=True))

    with pytest.raises(RuntimeError, match="all providers failed"):
        await service.chat("plan this", task_type="plan")

    assert p["groq"].calls == []
    assert p["gemini"].calls == []


# ── The declared chains ───────────────────────────────────────────────────────

def test_the_cheap_chains_are_ordered_cheapest_first():
    """A regression guard on the ordering itself, not just on one dispatch."""
    assert _TASK_CHAINS["classify"] == ["groq", "gemini", "claude"]
    assert _TASK_CHAINS["heal"] == ["groq", "gemini", "claude"]
    assert _TASK_CHAINS["plan"] == ["claude"]


async def test_an_unknown_task_type_falls_back_to_the_classify_chain():
    service, p = _service()

    result = await service.chat("hello", task_type="something_new")

    assert result == "answered by groq"
    assert p["groq"].calls[0]["max_tokens"] == 512, "the generic default, not classify's 150"


# ── Token budgets ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("task_type, expected", sorted(_MAX_TOKENS.items()))
async def test_each_task_type_caps_its_own_output(task_type, expected):
    """
    heal replies are one short JSON array; plan replies are a whole workflow.
    Sending plan's budget on every heal is how a cheap path stops being cheap.
    """
    service, p = _service()
    await service.chat("hello", task_type=task_type)

    answering = next(d for d in p.values() if d.calls)
    assert answering.calls[0]["max_tokens"] == expected


async def test_the_system_prompt_reaches_the_provider():
    service, p = _service()

    await service.chat("user text", task_type="heal", system="you are a healer")

    assert p["groq"].calls[0]["system"] == "you are a healer"
    assert p["groq"].calls[0]["prompt"] == "user text"
