"""
healer/interfaces.py — Contracts for the self-healing subsystem.

Design Patterns:
  Strategy  : HealerStrategy — swap AiHealer for a mock/stub in tests
  ISP       : small focused interface; callers depend only on heal()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.interfaces import StepConfig


# ──────────────────────────────────────────────────────────
# VALUE OBJECTS
# ──────────────────────────────────────────────────────────

@dataclass
class DomPayload:
    """
    Result of DOMSnapshotCascade.capture().

    strategy_used   one of: "embed_direct" | "embed_candidates" | "scoped" | "aria"
    content         JSON string passed to the AI prompt (empty for embed_direct)
    healed_cfg      ready-to-use cfg dict when strategy_used == "embed_direct"; else None
    token_estimate  rough token count of content (0 for embed_direct)
    """
    strategy_used: str
    content: str
    healed_cfg: Optional[dict] = None
    token_estimate: int = 0


# ──────────────────────────────────────────────────────────
# EXCEPTIONS
# ──────────────────────────────────────────────────────────

class HealingError(Exception):
    """Raised when all healer providers fail to produce a valid replacement."""


# ──────────────────────────────────────────────────────────
# STRATEGY — Healer
# ──────────────────────────────────────────────────────────

class HealerStrategy(ABC):
    """
    Strategy pattern: each implementation decides how to produce replacement
    steps when a workflow step fails after all retries.

    Contract:
      heal(step, error, dom) -> list[StepConfig]
        Returns one or more replacement StepConfig objects.
        Raises HealingError if healing is not possible.

    Implementations must be stateless across calls (thread-safe for concurrent
    workflow runs).
    """

    @abstractmethod
    async def heal(
        self,
        step: "StepConfig",
        error: str,
        dom: DomPayload,
    ) -> list["StepConfig"]:
        """
        Produce replacement steps for a failed step.

        step   the StepConfig that failed
        error  the error message / traceback string
        dom    DOM context captured by DOMSnapshotCascade

        Returns a non-empty list of StepConfig replacements.
        Raises HealingError if no replacement can be produced.
        """
