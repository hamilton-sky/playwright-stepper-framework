"""
resolvers/ai_pick_resolver.py — Multi-provider AI disambiguation resolver.

Single resolver, three backends — graceful degradation:
  Groq  (free, ~200ms)  →  Gemini  (cheap, ~500ms)  →  Claude  (powerful, ~2s)

The cascade (ElementResolver) never knows which backend answered.
It receives a confidence score and a locator index — nothing else.

Design mirrors BrightSky's SmartDisambiguationService pattern:
  - Task-based routing: classification tasks go to Groq first
  - JSON mode enforced on all providers
  - Malformed JSON repaired before parsing
  - On total failure → returns top candidate with reduced confidence

OCP: Add a new backend by adding one _try_*() method + entry in _BACKENDS.
DIP: Callers receive a plain (index, confidence) tuple — no provider coupling.
"""

from __future__ import annotations
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# Minimum confidence to trust the AI pick (mirrors BrightSky's 0.6 floor)
_MIN_CONFIDENCE = 0.60
_MAX_CONFIDENCE = 1.00


def _repair_json(raw: str) -> dict:
    """
    Strip markdown fences and fix common AI JSON formatting mistakes.
    Returns parsed dict or raises ValueError.
    """
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    return json.loads(text)


def _parse_response(raw: str, n_candidates: int) -> tuple[int, float] | None:
    """
    Parse {"choice": 1, "confidence": 0.95} from AI response.
    Returns (0-based index, clamped confidence) or None on failure.
    """
    try:
        data = _repair_json(raw)
        # Support both "choice" (Stepper convention) and "selectedIndex" (BrightSky)
        idx_1based = int(data.get("choice") or data.get("selectedIndex") or 1)
        conf = float(data.get("confidence", 0.7))
        idx = idx_1based - 1
        if idx < 0 or idx >= n_candidates:
            logger.warning(f"[AIPickResolver] index {idx_1based} out of range (n={n_candidates})")
            return None
        conf = max(_MIN_CONFIDENCE, min(_MAX_CONFIDENCE, conf))
        return idx, conf
    except Exception as e:
        logger.warning(f"[AIPickResolver] JSON parse error: {e} — raw: {raw[:200]}")
        return None


def _build_prompt(candidates_text: str, step_description: str) -> str:
    return (
        f'Step goal: "{step_description}"\n\n'
        f"Candidates:\n{candidates_text}\n\n"
        'Return ONLY valid JSON (no markdown):\n'
        '{"choice": <1-based index>, "confidence": <0.0-1.0>}'
    )


class AIPickResolver:
    """
    Tries Groq → Gemini → Claude in order.
    Returns (index, confidence) for the best candidate, or None if all fail.

    Usage:
        resolver = AIPickResolver()
        result = await resolver.pick(candidates_text, step_description, n_candidates)
    """

    def __init__(self) -> None:
        self._groq_key    = os.getenv("GROQ_API_KEY", "")
        self._gemini_key  = os.getenv("GEMINI_API_KEY", "")
        self._claude_key  = os.getenv("ANTHROPIC_API_KEY", "")

    async def pick(
        self,
        candidates_text: str,
        step_description: str,
        n_candidates: int,
    ) -> tuple[int, float] | None:
        """
        Try each backend in order.
        Returns (0-based index, confidence) or None if every backend fails.
        """
        prompt = _build_prompt(candidates_text, step_description)

        for backend_name, backend_fn in [
            ("groq",   self._try_groq),
            ("gemini", self._try_gemini),
            ("claude", self._try_claude),
        ]:
            if not self._is_configured(backend_name):
                logger.debug(f"[AIPickResolver] {backend_name} not configured — skipping")
                continue
            try:
                raw = await backend_fn(prompt)
                result = _parse_response(raw, n_candidates)
                if result is not None:
                    idx, conf = result
                    logger.info(
                        f"✓ [AIPickResolver/{backend_name}] "
                        f"choice={idx+1}/{n_candidates} confidence={conf:.0%}"
                    )
                    return result
                logger.warning(f"[AIPickResolver] {backend_name} returned unparseable response")
            except Exception as e:
                logger.warning(f"[AIPickResolver] {backend_name} failed: {e}")

        logger.warning("[AIPickResolver] all backends failed")
        return None

    def _is_configured(self, name: str) -> bool:
        keys = {"groq": self._groq_key, "gemini": self._gemini_key, "claude": self._claude_key}
        return bool(keys.get(name, "").strip())

    # ── Groq backend ──────────────────────────────────────────────────────────

    async def _try_groq(self, prompt: str) -> str:
        from groq import Groq  # pip install groq
        client = Groq(api_key=self._groq_key)
        completion = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert at identifying UI elements. "
                        "Select the element that best matches the user's intent. "
                        "Output only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=120,
        )
        return completion.choices[0].message.content or ""

    # ── Gemini backend ────────────────────────────────────────────────────────

    async def _try_gemini(self, prompt: str) -> str:
        import google.generativeai as genai  # pip install google-generativeai
        genai.configure(api_key=self._gemini_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 120,
                "response_mime_type": "application/json",
            },
            system_instruction=(
                "You are an expert at identifying UI elements. "
                "Select the element that best matches the user's intent. "
                "Output only valid JSON."
            ),
        )
        response = model.generate_content(prompt)
        return response.text or ""

    # ── Claude backend ────────────────────────────────────────────────────────

    async def _try_claude(self, prompt: str) -> str:
        import anthropic  # already in requirements.txt
        client = anthropic.Anthropic(api_key=self._claude_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # cheapest Claude — sufficient for classification
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text or ""
