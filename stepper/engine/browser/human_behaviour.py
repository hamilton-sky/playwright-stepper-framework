"""
engine/browser/human_behaviour.py — Runtime interaction humanisation service.

Applies jitter to delays, hover dwell before clicks, and inter-step pauses so
interaction timing is non-deterministic and harder to fingerprint as a bot.

Complement to AntiDetection (setup-time) — this runs per-action, per-step.

Configuration via environment variables (all optional):
  JITTER_FACTOR         Float 0.0–1.0, default 0.30 (±30% on every delay)
  HOVER_BEFORE_CLICK    "false" to disable hover dwell, default "true"
  HOVER_MS              Base hover dwell in ms, default 80
  INTER_STEP_DELAY_MS   Pause between workflow steps in ms, default 150

Set JITTER_FACTOR=0 to disable all jitter (e.g. in CI / fast mode).

AI extension: set strategy="claude" or "ml" on HumanBehaviourConfig when a
TimingStrategy implementation is available — same pattern as ElementResolver.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Extensibility: TimingStrategy ABC ─────────────────────────────────────────

class TimingStrategy(ABC):
    """
    Swap the timing algorithm without changing HumanBehaviour or BasePage.

    Future implementations:
      ClaudeTimingStrategy — Claude API generates delays from page context
      MLTimingStrategy     — trained model predicts delay from element type
    """

    @abstractmethod
    def next_delay_ms(self, base_ms: int, context: dict | None = None) -> float:
        """Return actual delay in ms given a base value and optional context."""


class DeterministicJitter(TimingStrategy):
    """Default: random.uniform within ±jitter_factor of base_ms."""

    def __init__(self, jitter_factor: float = 0.30):
        self._factor = jitter_factor

    def next_delay_ms(self, base_ms: int, context: dict | None = None) -> float:
        if self._factor == 0:
            return float(base_ms)
        lo = base_ms * (1 - self._factor)
        hi = base_ms * (1 + self._factor)
        return random.uniform(lo, hi)


# ── Configuration ──────────────────────────────────────────────────────────────

@dataclass
class HumanBehaviourConfig:
    """
    Controls how HumanBehaviour humanises interaction timing.

    All fields have env-var overrides so CI can disable jitter without
    changing source code (set JITTER_FACTOR=0).
    """
    jitter_factor: float = 0.30
    hover_before_click: bool = True
    hover_ms: int = 80
    inter_step_delay_ms: int = 150
    strategy: str = "deterministic"   # "deterministic" | "ai" (future)

    @classmethod
    def from_env(cls) -> "HumanBehaviourConfig":
        return cls(
            jitter_factor=float(os.environ.get("JITTER_FACTOR", 0.30)),
            hover_before_click=os.environ.get(
                "HOVER_BEFORE_CLICK", "true"
            ).strip().lower() != "false",
            hover_ms=int(os.environ.get("HOVER_MS", 80)),
            inter_step_delay_ms=int(os.environ.get("INTER_STEP_DELAY_MS", 150)),
        )


# ── Service ────────────────────────────────────────────────────────────────────

class HumanBehaviour:
    """
    Stateless runtime humanisation service.

    Injected into BasePage and StepRunner so every interaction and every
    step gets a naturally varied timing profile.

    Usage (BasePage):
        await asyncio.sleep(self._behaviour.jitter(self.delays.between_actions_ms))
        await self._behaviour.hover_before_click(locator)

    Usage (StepRunner):
        await self._behaviour.inter_step_delay()

    Disable for CI / fast mode:
        HumanBehaviour(HumanBehaviourConfig(jitter_factor=0,
                                             hover_before_click=False,
                                             inter_step_delay_ms=0))
    """

    def __init__(self, config: HumanBehaviourConfig | None = None):
        self._cfg = config or HumanBehaviourConfig.from_env()
        self._strategy: TimingStrategy = DeterministicJitter(self._cfg.jitter_factor)

    def jitter(self, base_ms: int) -> float:
        """
        Return a jittered delay in seconds.

        base_ms=300, jitter_factor=0.30  →  0.210 … 0.390 seconds
        base_ms=300, jitter_factor=0.0   →  0.300 seconds exactly
        """
        return self._strategy.next_delay_ms(base_ms) / 1000

    async def hover_before_click(self, locator) -> None:
        """
        Hover over a locator for a jittered dwell time before the caller clicks.
        Logs the viewport coordinates and the duration of the hover.
        """
        if not self._cfg.hover_before_click:
            logger.debug("HumanBehaviour: hover disabled in config")
            return
        try:
            box = await locator.bounding_box()
            coord_str = f"at ({box['x']:.0f}, {box['y']:.0f})" if box else "at unknown position"
            await locator.hover(timeout=3_000)
            dwell_s = self.jitter(self._cfg.hover_ms)
            logger.debug(f"HumanBehaviour: hovered {coord_str} for {dwell_s*1000:.0f}ms")
            await asyncio.sleep(dwell_s)
        except Exception as exc:
            logger.debug(f"HumanBehaviour: hover failed: {exc}")
    
    async def inter_step_delay(self) -> None:
        """
        Insert a jittered pause between workflow steps.
        """
        if self._cfg.inter_step_delay_ms <= 0:
            return
            
        delay_s = self.jitter(self._cfg.inter_step_delay_ms)
        logger.debug(f"HumanBehaviour: inter-step pause of {delay_s*1000:.0f}ms")
        await asyncio.sleep(delay_s)