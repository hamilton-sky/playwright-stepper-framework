"""
ai/service.py — Single LLM entry point; routes by task_type to provider chain.

Adding a new provider = one new class in providers.py + one entry here.
No callers change.

Task chains (cheapest → most capable):
    classify  Groq → Gemini → Claude   (short JSON, ~150 tokens out)
    plan      Claude only               (complex multi-step reasoning)
    heal      Groq → Gemini → Claude   (short JSON, ~1024 tokens out)
    heal_big  Claude big model only     (paid rung after the cheap tier, ~1024 tokens out)
"""

from __future__ import annotations

import logging

from stepper.engine.ai.providers import ClaudeProvider, GeminiProvider, GroqProvider

logger = logging.getLogger(__name__)

# The big-model rung's model id (claude-sonnet-4-20250514 was retired 2026-06-15)
_BIG_MODEL = "claude-sonnet-5-5"

# Provider names ordered cheapest-first per task type
_TASK_CHAINS: dict[str, list[str]] = {
    "classify": ["groq", "gemini", "claude"],
    "plan":     ["claude"],
    "heal":     ["groq", "gemini", "claude"],
    "heal_big": ["claude_big"],
}

# Max output tokens per task type
_MAX_TOKENS: dict[str, int] = {
    "classify": 150,
    "plan":     2000,
    "heal":     1024,
    "heal_big": 1024,
}


class AIService:
    """
    Single LLM entry point. Tries providers in cheapest-first order for the
    given task_type, returning the first successful response.

    Usage:
        svc = AIService()
        text = await svc.chat(prompt, task_type="heal", system="...")
    """

    def __init__(self) -> None:
        self._providers: dict[str, GroqProvider | GeminiProvider | ClaudeProvider] = {
            "groq":   GroqProvider(),
            "gemini": GeminiProvider(),
            "claude": ClaudeProvider(),
            "claude_big": ClaudeProvider(model=_BIG_MODEL),
        }

    async def chat(
        self,
        prompt: str,
        task_type: str = "classify",
        system: str = "",
    ) -> str:
        """
        Try each provider in the task_type chain; return the first success.
        Raises RuntimeError if every provider in the chain fails or is unconfigured.
        """
        chain = _TASK_CHAINS.get(task_type, _TASK_CHAINS["classify"])
        max_tokens = _MAX_TOKENS.get(task_type, 512)

        for name in chain:
            provider = self._providers[name]
            if not provider.is_configured:
                logger.debug(f"[AIService/{task_type}] {name} not configured — skipping")
                continue
            try:
                result = await provider.chat(prompt, system=system, max_tokens=max_tokens)
                logger.info(f"[AIService/{task_type}] answered by {name}")
                logger.debug(f"[AIService/{task_type}] raw response: {result}")
                return result
            except Exception as e:
                logger.warning(f"[AIService/{task_type}] {name} failed: {e}")

        raise RuntimeError(
            f"[AIService] all providers failed for task_type='{task_type}'. "
            f"Chain tried: {chain}"
        )
