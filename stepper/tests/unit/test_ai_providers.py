"""
Provider-level logic that the AIService chain tests do not reach.

Two things here never touch a network and are worth pinning.

_strip_fences is the one that bites. Models wrap JSON in a markdown fence
whether or not you asked, and AiHealer._parse feeds the result straight to
json.loads — so a fence that survives is reported as "AI returned invalid
JSON", which points the reader at the model rather than at the three lines of
regex that were supposed to have removed it.

is_configured decides whether a provider is skipped or attempted. Reading it
wrong means either a provider that is never tried despite having a key, or one
that is tried without one and fails on every call.
"""
from __future__ import annotations

import pytest

from stepper.engine.ai.providers import (
    ClaudeProvider,
    GeminiProvider,
    GroqProvider,
    _strip_fences,
)


# ── Fence stripping ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ('```json\n{"a": 1}\n```',  '{"a": 1}'),
        ('```JSON\n{"a": 1}\n```',  '{"a": 1}'),   # case-insensitive
        ('```\n{"a": 1}\n```',      '{"a": 1}'),   # bare fence
        ('```json {"a": 1} ```',    '{"a": 1}'),   # all on one line
        ('  ```json\n{"a": 1}\n```  ', '{"a": 1}'),  # surrounding whitespace
        ('{"a": 1}',                '{"a": 1}'),   # already clean
        ('',                        ''),
    ],
)
def test_a_fenced_reply_comes_back_as_parseable_json(raw, expected):
    assert _strip_fences(raw) == expected


def test_stripping_a_fence_leaves_json_that_actually_parses():
    """The property that matters, stated as the caller experiences it."""
    import json

    assert json.loads(_strip_fences('```json\n[{"action": "click"}]\n```')) == [
        {"action": "click"}
    ]


def test_a_fence_inside_the_payload_is_not_treated_as_the_wrapper():
    """
    Only the leading and trailing fences go. A step whose input_value happens to
    contain backticks must survive intact.
    """
    raw = '```json\n{"input_value": "run ```code``` now"}\n```'

    assert _strip_fences(raw) == '{"input_value": "run ```code``` now"}'


# ── is_configured ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "provider_cls, env_var",
    [
        (GroqProvider,   "GROQ_API_KEY"),
        (GeminiProvider, "GEMINI_API_KEY"),
        (ClaudeProvider, "ANTHROPIC_API_KEY"),
    ],
)
def test_a_provider_with_no_key_is_not_configured(provider_cls, env_var, monkeypatch):
    monkeypatch.delenv(env_var, raising=False)

    assert provider_cls().is_configured is False


@pytest.mark.parametrize(
    "provider_cls, env_var",
    [
        (GroqProvider,   "GROQ_API_KEY"),
        (GeminiProvider, "GEMINI_API_KEY"),
        (ClaudeProvider, "ANTHROPIC_API_KEY"),
    ],
)
def test_a_provider_with_a_key_is_configured(provider_cls, env_var, monkeypatch):
    monkeypatch.setenv(env_var, "sk-test-key")

    assert provider_cls().is_configured is True


@pytest.mark.parametrize("blank", ["", "   ", ","])
def test_a_blank_groq_key_does_not_count_as_configured(blank, monkeypatch):
    """
    An env var set to empty is the usual shape of a half-filled .env. Treating
    it as configured means every heal attempts groq first and fails first.
    """
    monkeypatch.setenv("GROQ_API_KEY", blank)

    assert GroqProvider().is_configured is False


# ── Groq key rotation ─────────────────────────────────────────────────────────

def test_groq_splits_a_comma_separated_key_list(monkeypatch):
    """Each key carries its own daily quota; rotation is why the list is allowed."""
    monkeypatch.setenv("GROQ_API_KEY", "key1,key2,key3")

    provider = GroqProvider()

    assert provider.is_configured is True
    assert provider._keys == ["key1", "key2", "key3"]


def test_groq_ignores_whitespace_and_empty_entries_in_the_key_list(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", " key1 , ,key2,, key3 ")

    assert GroqProvider()._keys == ["key1", "key2", "key3"]


def test_a_single_groq_key_is_still_a_list_of_one(monkeypatch):
    """The rotation code indexes into _keys unconditionally."""
    monkeypatch.setenv("GROQ_API_KEY", "solo-key")

    assert GroqProvider()._keys == ["solo-key"]
