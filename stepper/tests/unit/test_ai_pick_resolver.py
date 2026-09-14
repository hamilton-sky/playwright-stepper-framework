"""
AIPickResolver — Phase 3 of the resolution cascade, the tier that costs money.

By the time this runs, the deterministic strategies have found nothing unique
and the semantic filter has left more than one candidate standing. It asks a
model to choose, and hands the cascade back an index and a confidence.

Everything tested here is offline. The three `_try_*` methods each import a
vendor SDK and open a socket; they are replaced. What is worth pinning is the
logic around them — the cascade order, the parsing of an untrusted reply, and
the key rotation, which is the subtlest code in the file and the easiest to
break without noticing.

One behaviour documented rather than endorsed: confidence is clamped *up* to
0.60 as well as down to 1.00, so a model reporting 5% certainty is recorded as
60%. That floor sits below the cascade's 0.70 act threshold, so it does not by
itself cause a bad pick to be acted on — see the test that says so.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from stepper.engine.resolvers.ai_pick_resolver import (
    AIPickResolver,
    _MAX_CONFIDENCE,
    _MIN_CONFIDENCE,
    _build_prompt,
    _parse_response,
    _repair_json,
)


@pytest.fixture
def resolver(monkeypatch) -> AIPickResolver:
    """A resolver with all three backends configured and none of them real."""
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-key")
    return AIPickResolver()


def _stub_backends(resolver: AIPickResolver, monkeypatch, **replies):
    """
    Replace each _try_* with a recorder. A str reply is returned; an Exception
    instance is raised. Returns the call log.
    """
    calls: list[str] = []

    def make(name):
        async def fn(prompt):
            calls.append(name)
            reply = replies.get(name, '{"choice": 1, "confidence": 0.9}')
            if isinstance(reply, Exception):
                raise reply
            return reply
        return fn

    for name in ("groq", "gemini", "claude"):
        monkeypatch.setattr(resolver, f"_try_{name}", make(name))
    return calls


def _fake_groq_client(content: str = '{"choice": 1}'):
    """The shape _try_groq reaches into: client.chat.completions.create(...)."""
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: completion)
        )
    )


def _install_fake_groq(monkeypatch, factory):
    """
    Put a fake `groq` module in sys.modules. _try_groq imports it inside the
    function, so this is enough — and it works whether or not the real SDK is
    installed, which matters because the unit suite must not depend on it.
    """
    monkeypatch.setitem(
        sys.modules, "groq",
        SimpleNamespace(
            Groq=factory,
            RateLimitError=type("RateLimitError", (Exception,), {}),
        ),
    )


# ── Repairing the reply ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw",
    [
        '{"choice": 2, "confidence": 0.9}',
        '```json\n{"choice": 2, "confidence": 0.9}\n```',
        '```\n{"choice": 2, "confidence": 0.9}\n```',
        '   ```JSON {"choice": 2, "confidence": 0.9} ```   ',
    ],
)
def test_a_fenced_reply_still_parses(raw):
    """Every provider is asked for JSON mode and some still wrap it anyway."""
    assert _repair_json(raw) == {"choice": 2, "confidence": 0.9}


def test_an_unrepairable_reply_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        _repair_json("I think the second one looks right")


# ── Parsing choice and confidence ─────────────────────────────────────────────

def test_the_reply_is_one_based_and_the_cascade_wants_zero_based():
    """
    The prompt asks for a 1-based index because models count from one reliably
    and from zero unreliably. Off-by-one here picks the wrong element.
    """
    assert _parse_response('{"choice": 1, "confidence": 0.9}', 3) == (0, 0.9)
    assert _parse_response('{"choice": 3, "confidence": 0.9}', 3) == (2, 0.9)


def test_the_brightsky_key_is_accepted_too():
    """`selectedIndex` is the other convention this parser tolerates."""
    assert _parse_response('{"selectedIndex": 2, "confidence": 0.8}', 3) == (1, 0.8)


@pytest.mark.parametrize("choice", [0, 4, 99, -1])
def test_an_out_of_range_choice_is_refused(choice):
    """
    Acting on an index the candidate list does not have would be an IndexError
    at best and the wrong element at worst. None sends the cascade to its
    fallback instead.
    """
    assert _parse_response(json.dumps({"choice": choice, "confidence": 0.9}), 3) is None


@pytest.mark.parametrize("key", ["choice", "selectedIndex"])
def test_a_zero_index_is_refused_rather_than_silently_becoming_one(key):
    """
    Regression: the index was read with `int(data.get("choice") or
    data.get("selectedIndex") or 1)`. 0 is falsy, so {"choice": 0} fell through
    the whole chain and came out as 1 — the out-of-range guard below could never
    see it, because the rewrite happened first.

    It read as harmless because 1 maps to index 0 and the first candidate is
    what a 0-based model meant anyway. It is not: a model answering 0 for "none
    of these" got the first candidate picked for it, at whatever confidence it
    had reported.
    """
    assert _parse_response(json.dumps({key: 0, "confidence": 0.9}), 3) is None


def test_an_absent_index_still_defaults_to_the_first_candidate():
    """The `or 1` fallback was doing one useful thing; keep it for a real absence."""
    assert _parse_response('{"confidence": 0.9}', 3) == (0, 0.9)


def test_a_missing_confidence_defaults_rather_than_failing():
    result = _parse_response('{"choice": 1}', 2)
    assert result == (0, 0.7)


@pytest.mark.parametrize(
    "reported, recorded",
    [
        (1.5,  _MAX_CONFIDENCE),   # clamped down
        (1.0,  _MAX_CONFIDENCE),
        (0.75, 0.75),              # untouched in range
        (0.05, _MIN_CONFIDENCE),   # clamped UP — see the module docstring
        (-1.0, _MIN_CONFIDENCE),
    ],
)
def test_confidence_is_clamped_at_both_ends(reported, recorded):
    result = _parse_response(json.dumps({"choice": 1, "confidence": reported}), 2)
    assert result is not None
    assert result[1] == recorded


def test_the_confidence_floor_sits_below_the_cascade_s_act_threshold():
    """
    Clamping *up* would be dangerous if the floor reached the threshold the
    cascade acts on. It does not: a no-confidence pick lands at 0.60, and
    CONFIDENCE_AI_PICK is higher, so it still does not auto-act.
    """
    from stepper.engine.interfaces import CONFIDENCE_AI_PICK

    assert _MIN_CONFIDENCE < CONFIDENCE_AI_PICK


@pytest.mark.parametrize(
    "raw",
    ['not json at all', '', '{"choice": "second"}', '[]', 'null'],
)
def test_a_malformed_reply_is_none_not_an_exception(raw):
    """
    pick() treats None as "this backend could not help" and moves on. Raising
    here would abort the cascade instead of degrading through it.
    """
    assert _parse_response(raw, 3) is None


# ── The prompt ────────────────────────────────────────────────────────────────

def test_the_prompt_carries_the_goal_and_the_candidates():
    prompt = _build_prompt("1. Log in button\n2. Login link", "click the login button")

    assert "click the login button" in prompt
    assert "Log in button" in prompt
    assert "1-based index" in prompt, "the parser depends on the model counting from 1"


# ── The backend cascade ───────────────────────────────────────────────────────

async def test_the_cheapest_backend_answers_and_the_rest_are_not_called(resolver, monkeypatch):
    calls = _stub_backends(resolver, monkeypatch)

    assert await resolver.pick("1. Login", "click login", 1) == (0, 0.9)
    assert calls == ["groq"]


async def test_a_failing_backend_falls_through(resolver, monkeypatch):
    calls = _stub_backends(resolver, monkeypatch, groq=RuntimeError("groq down"))

    assert await resolver.pick("1. Login", "click login", 1) == (0, 0.9)
    assert calls == ["groq", "gemini"]


async def test_an_unparseable_reply_falls_through_like_a_failure(resolver, monkeypatch):
    """
    A backend that answers with prose has not helped. Treating a 200 response as
    success just because it did not raise would end the cascade on nothing.
    """
    calls = _stub_backends(resolver, monkeypatch, groq="I'd pick the second one")

    assert await resolver.pick("1. a\n2. b", "click login", 2) == (0, 0.9)
    assert calls == ["groq", "gemini"]


async def test_every_backend_failing_returns_none(resolver, monkeypatch):
    """
    None is the cascade's signal to fall back to the top semantic result. It
    must not raise — an unresolvable element is a step outcome, not a crash.
    """
    _stub_backends(
        resolver, monkeypatch,
        groq=RuntimeError("down"), gemini=RuntimeError("down"), claude=RuntimeError("down"),
    )

    assert await resolver.pick("1. Login", "click login", 1) is None


async def test_unconfigured_backends_are_skipped_not_attempted(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-key")
    resolver = AIPickResolver()
    calls = _stub_backends(resolver, monkeypatch)

    assert await resolver.pick("1. Login", "click login", 1) == (0, 0.9)
    assert calls == ["claude"], "only the configured backend should be tried"


async def test_no_backend_configured_returns_none(monkeypatch):
    """The normal state on an install with no keys. It must degrade, not raise."""
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    resolver = AIPickResolver()
    calls = _stub_backends(resolver, monkeypatch)

    assert await resolver.pick("1. Login", "click login", 1) is None
    assert calls == []


# ── is_configured ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("blank", ["", "   ", ","])
def test_a_blank_groq_key_is_not_configured(blank, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", blank)

    assert AIPickResolver()._is_configured("groq") is False


@pytest.mark.parametrize("name", ["gemini", "claude"])
def test_a_whitespace_only_key_is_not_configured(name, monkeypatch):
    monkeypatch.setenv({"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}[name], "   ")

    assert AIPickResolver()._is_configured(name) is False


# ── Groq key rotation ─────────────────────────────────────────────────────────
#
# The subtlest code in the module. Each key carries its own daily quota, so the
# pointer advances after every *successful* call rather than only on a 429 —
# load spreads from the first request instead of after the first key burns out.

def test_multiple_keys_are_split_on_commas(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", " k1 , k2 ,, k3 ")

    assert AIPickResolver()._groq_keys == ["k1", "k2", "k3"]
    assert AIPickResolver()._groq_key_idx == 0


async def test_the_pointer_advances_after_a_successful_call(monkeypatch):
    """
    Rotating only on rate-limit would hammer key 1 until it dies each day. The
    pointer moves on success, so three keys share the load evenly.
    """
    monkeypatch.setenv("GROQ_API_KEY", "k1,k2,k3")
    resolver = AIPickResolver()

    used: list[str] = []

    def fake_groq(api_key):
        used.append(api_key)
        return _fake_groq_client()

    _install_fake_groq(monkeypatch, fake_groq)

    for _ in range(4):
        await resolver._try_groq("prompt")

    assert used == ["k1", "k2", "k3", "k1"], "keys should round-robin, not repeat"


async def test_a_dead_key_rotates_to_the_next_within_one_call(monkeypatch):
    """
    One bad key must not fail the call while good keys remain — the loop tries
    each in turn before giving up.
    """
    monkeypatch.setenv("GROQ_API_KEY", "dead,alive")
    resolver = AIPickResolver()

    attempted: list[str] = []

    def fake_groq(api_key):
        attempted.append(api_key)
        if api_key == "dead":
            raise RuntimeError("401 unauthorized")
        return _fake_groq_client()

    _install_fake_groq(monkeypatch, fake_groq)

    assert await resolver._try_groq("prompt") == '{"choice": 1}'
    assert attempted == ["dead", "alive"]


async def test_every_key_failing_raises_the_last_error(monkeypatch):
    """pick() catches this and moves to the next backend; it must not return ''."""
    monkeypatch.setenv("GROQ_API_KEY", "k1,k2")
    resolver = AIPickResolver()

    def fake_groq(api_key):
        raise RuntimeError(f"{api_key} is down")

    _install_fake_groq(monkeypatch, fake_groq)

    with pytest.raises(RuntimeError, match="is down"):
        await resolver._try_groq("prompt")
