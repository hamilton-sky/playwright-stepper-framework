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
    from stepper.engine.interfaces import StepConfig


#: The free rung of the strict heal order: an exact-match cfg, no AI call.
FREE_TIER = "embed_direct"


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
      heal(step, error, dom, *, tried=()) -> list[StepConfig]
        Returns one or more replacement StepConfig objects.
        Raises HealingError if healing is not possible.
        `tried` names the rungs already tried for this step and failed, oldest
        first; the empty tuple (the default) means "heal as you always do".
      tier_for(dom, tried) -> str
        Names the rung heal() would use for these inputs. The heal loop records
        it and passes it back in `tried` when that rung fails. Default "healer".

    Implementations must be stateless across calls (thread-safe for concurrent
    workflow runs): the caller owns `tried`.
    """

    def tier_for(self, dom: DomPayload, tried: tuple[str, ...]) -> str:
        """The rung heal() would use for this payload after `tried` has failed."""
        return "healer"

    @abstractmethod
    async def heal(
        self,
        step: "StepConfig",
        error: str,
        dom: DomPayload,
        *,
        all_steps: list | None = None,
        current_index: int | None = None,
        context_vars: dict | None = None,
        tried: tuple[str, ...] = (),
    ) -> list["StepConfig"]:
        """
        Produce replacement steps for a failed step.

        step   the StepConfig that failed
        error  the error message / traceback string
        dom    DOM context captured by DOMSnapshotCascade
        tried  rungs already tried for this step and failed, oldest first

        Returns a non-empty list of StepConfig replacements.
        Raises HealingError if no replacement can be produced.
        """
