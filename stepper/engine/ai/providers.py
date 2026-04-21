"""
ai/providers.py — One class per LLM provider (~20 lines each).

Each provider exposes:
    is_configured  bool property — False when the required env var is absent
    chat(prompt, system, max_tokens) -> str  — stripped of markdown fences

Groq supports comma-separated GROQ_API_KEY values for round-robin rotation.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers that some models emit."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Groq ──────────────────────────────────────────────────────────────────────

class GroqProvider:
    """
    Groq/Qwen provider with round-robin key rotation.
    GROQ_API_KEY may be a comma-separated list: key1,key2,key3
    Each key carries 14,400 free req/day.
    """

    def __init__(self) -> None:
        raw = os.getenv("GROQ_API_KEY", "")
        self._keys: list[str] = [k.strip() for k in raw.split(",") if k.strip()]
        self._key_idx: int = 0

    @property
    def is_configured(self) -> bool:
        return bool(self._keys)

    async def chat(self, prompt: str, system: str = "", max_tokens: int = 512) -> str:
        from groq import Groq, RateLimitError  # pip install groq

        n = len(self._keys)
        start = self._key_idx
        last_exc: Exception | None = None

        for i in range(n):
            idx = (start + i) % n
            key = self._keys[idx]
            try:
                messages: list[dict] = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                client = Groq(api_key=key)
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=max_tokens,
                )
                self._key_idx = (idx + 1) % n
                logger.debug(f"[GroqProvider] used key {idx + 1}/{n}")
                return _strip_fences(completion.choices[0].message.content or "")

            except RateLimitError:
                logger.warning(f"[GroqProvider] key {idx + 1}/{n} rate-limited — rotating")
                last_exc = RateLimitError("rate limited")
            except Exception as e:
                logger.warning(f"[GroqProvider] key {idx + 1}/{n} failed: {e}")
                last_exc = e

        raise last_exc or RuntimeError("All Groq keys exhausted")


# ── Gemini ────────────────────────────────────────────────────────────────────

class GeminiProvider:
    """Gemini Flash provider. Reads GEMINI_API_KEY."""

    def __init__(self) -> None:
        self._key = os.getenv("GEMINI_API_KEY", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._key.strip())

    async def chat(self, prompt: str, system: str = "", max_tokens: int = 512) -> str:
        import google.generativeai as genai  # pip install google-generativeai

        genai.configure(api_key=self._key)
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
            },
            system_instruction=system or "You are a browser automation assistant. Output only valid JSON.",
        )
        response = model.generate_content(prompt)
        return _strip_fences(response.text or "")


# ── Claude ────────────────────────────────────────────────────────────────────

class ClaudeProvider:
    """Claude Haiku provider (cheapest Claude). Reads ANTHROPIC_API_KEY."""

    def __init__(self) -> None:
        self._key = os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._key.strip())

    async def chat(self, prompt: str, system: str = "", max_tokens: int = 512) -> str:
        import anthropic  # already in requirements.txt

        client = anthropic.Anthropic(api_key=self._key)
        kwargs: dict = dict(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        return _strip_fences(response.content[0].text or "")
