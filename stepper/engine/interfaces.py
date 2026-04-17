"""
interfaces.py — Abstract base classes for the entire system.

Design Patterns used here:
  - Strategy      : ActionStrategy, ResolverStrategy
  - Template Method: BaseAction defines the skeleton; subclasses fill steps
  - Observer      : StepObserver for UI/logging callbacks
  - Factory       : ActionFactory, ResolverFactory

SOLID:
  I (ISP) — small focused interfaces, not one god-interface
  D (DIP) — everything depends on abstractions, not concretions
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any, ClassVar, TYPE_CHECKING

# ──────────────────────────────────────────────────────────
# CONFIDENCE GATE THRESHOLDS
# CONFIDENCE_AUTO and CONFIDENCE_WARN are owned by poms/shared/constants.py
# (shared with the POM resolver helpers — single source of truth).
# Engine-only thresholds are declared here.
# ──────────────────────────────────────────────────────────
from engine.browser.human_behaviour import HumanBehaviour
from poms.shared.constants import CONFIDENCE_AUTO, CONFIDENCE_WARN  # re-exported

CONFIDENCE_SEMANTIC:    float = 0.80   # semantic resolver min score to count as match
CONFIDENCE_AI_PICK:     float = 0.70   # AI picker min score to accept a candidate
CONFIDENCE_DESCRIPTION: float = 0.40   # description-fallback resolver min similarity


# ──────────────────────────────────────────────────────────
# CONFIGURATION VALUE OBJECTS
# ──────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────
# VALUE OBJECTS
# ──────────────────────────────────────────────────────────

@dataclass
class StepConfig:
    """Immutable config for one automation step."""
    action: str
    description: str = ""
    url: str = ""
    element: dict = field(default_factory=dict)
    input_value: str = ""
    wait_for: str = ""
    extra: dict = field(default_factory=dict)   # open bag for action-specific keys
    when: dict | None = None                    # optional condition — None means always run
    retry: int = 0                              # number of retries on failure (0 = no retry)
    retry_delay_ms: int = 1000                  # delay between retries in milliseconds
    continue_on_failure: bool = False           # if True, flow continues even when step fails
    skip_screenshot: bool = False               # if True, auto-screenshot is suppressed (useful inside for_each loops)


@dataclass
class ResolveResult:
    """Result of an element resolution attempt."""
    found: bool
    locator: Any = None          # Playwright Locator
    confidence: float = 0.0
    method: str = "none"

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= CONFIDENCE_AUTO

    @property
    def is_acceptable(self) -> bool:
        return self.confidence >= 0.50


@dataclass
class StepResult:
    """Result of executing one step."""
    step: StepConfig
    status: str            # "passed" | "failed" | "skipped" | "warned"
    error: str = ""
    screenshot: str = ""
    screenshots: list[str] = field(default_factory=list)  # all screenshots from multi-shot actions
    confidence: float = 0.0
    duration_ms: float = 0.0
    output: dict = field(default_factory=dict)  # step-produced data saved to results.json


# ──────────────────────────────────────────────────────────
# EXECUTION CONTEXT
# ──────────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    """
    Typed shared state that flows between steps.

    Before: context["collected_items"] = urls   ← typo "collected_item" silently breaks things
    After:  context.collected_items = urls       ← typo caught by IDE / mypy immediately

    Named fields cover the four things actions actually share:
        collected_items  - URLs (or item dicts) produced by collect_items
        extracted_data   - items produced by extract_data
        paginated_data   - accumulated items produced by paginate
        counts           - named integer counters  e.g. {"count_before": 12}

    Note: Legacy page._collected_books is accessed by ForEachItemAction as a
    page-attribute fallback — not a typed field on this class.

    when_eval compatibility: implements get() and __contains__ so the
    condition evaluator requires zero changes.

    Domain swap: subclass ExecutionContext with extra typed fields for your
    own domain (e.g. GoodreadsContext, AmazonContext) and pass it into
    StepRunner.run(). The runner and all standard actions work unchanged.
    """

    collected_items: list[Any]        = field(default_factory=list)  # list[dict] with url/year, or list[str] for legacy
    extracted_data:  list[Any]       = field(default_factory=list)
    paginated_data:  list[Any]       = field(default_factory=list)
    counts:          dict[str, int]  = field(default_factory=dict)

    # ClassVar — not treated as a dataclass field, not in __init__
    _NAMED: ClassVar[frozenset[str]] = frozenset(
        {"collected_items", "extracted_data", "paginated_data"}
    )

    # ── Type-safe count helpers ──────────────────────────────────────────────

    def set_count(self, key: str, value: int) -> None:
        """Store a named counter.  e.g. ctx.set_count("count_before", 12)"""
        self.counts[key] = value

    def get_count(self, key: str, default: int = 0) -> int:
        """Read a named counter safely."""
        return self.counts.get(key, default)

    def has_count(self, key: str) -> bool:
        return key in self.counts

    # ── when_eval / backward-compat dict-like API ────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Dict-like get() so when_eval conditions work without changes.
        Checks named fields first, then counts.
        """
        if key in self._NAMED:
            val = getattr(self, key)
            return val if val else default
        return self.counts.get(key, default)

    def __contains__(self, key: str) -> bool:
        """Supports  'key in context'  checks in AssertCountAction."""
        if key in self._NAMED:
            return bool(getattr(self, key))
        return key in self.counts


# ──────────────────────────────────────────────────────────
# STRATEGY — Element Resolver
# ──────────────────────────────────────────────────────────

class ResolverStrategy(ABC):
    """
    Strategy pattern: each resolver knows ONE way to find an element.
    The cascade in ElementResolver tries them in priority order.
    """

    @property
    @abstractmethod
    def priority(self) -> int:
        """Lower = tried first."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging."""

    @abstractmethod
    async def collect(self, page, cfg: dict) -> list:
        """
        Returns a list of Playwright Locators matching cfg.
        Empty list = strategy cannot help here.
        """


# ──────────────────────────────────────────────────────────
# STRATEGY — Action
# ──────────────────────────────────────────────────────────

class ActionStrategy(ABC):
    """
    Strategy pattern: each action type (click, fill, navigate…)
    is a self-contained class.

    Template Method is applied inside execute():
      1. pre_execute  (hook — default no-op)
      2. _execute     (abstract — must implement)
      3. post_execute (hook — default no-op)

    read_only = True  → action does not mutate browser/server state.
                        Safe to run inside ParallelAction.
    read_only = False → action writes to DOM, server, or file system.
                        ParallelAction will refuse to run it.
    """

    read_only: bool = False  # subclasses override to True when safe to parallelize

    @property
    @abstractmethod
    def action_name(self) -> str:
        """Must match the 'action' field in step JSON."""

    async def execute(self, page, step: StepConfig, resolver,
                      context: "ExecutionContext | None" = None, behaviour: HumanBehaviour = None) -> StepResult:
        """Template method — do NOT override this."""
        ctx = context if context is not None else ExecutionContext()
        await self.pre_execute(page, step)
        result = await self._execute(page, step, resolver, ctx)
        await self.post_execute(page, step, result)
        return result

    @abstractmethod
    async def _execute(self, page, step: StepConfig, resolver,
                       context: "ExecutionContext" ,behaviour: HumanBehaviour) -> StepResult:
        """Core logic — subclasses implement this."""

    async def pre_execute(self, page, step: StepConfig):
        """Hook: runs before _execute. Override for setup."""

    async def post_execute(self, page, step: StepConfig, result: StepResult):
        """Hook: runs after _execute. Override for teardown / screenshots."""


# ──────────────────────────────────────────────────────────
# STRATEGY — Reporter
# ──────────────────────────────────────────────────────────

class ReporterStrategy(ABC):
    """
    Strategy pattern: swap between Allure, JSON, HTML, console reporters.
    """

    @abstractmethod
    def start_suite(self, name: str): ...

    @abstractmethod
    def record_step(self, result: StepResult): ...

    @abstractmethod
    def finish_suite(self) -> str:
        """Returns path or summary string."""


# ──────────────────────────────────────────────────────────
# OBSERVER — Step lifecycle events
# ──────────────────────────────────────────────────────────

class StepObserver(ABC):
    """
    Observer pattern: UI, logger, and reporter all subscribe to step events
    without the runner knowing about them.
    """

    @abstractmethod
    def on_step_start(self, idx: int, step: StepConfig): ...

    @abstractmethod
    def on_step_done(self, idx: int, result: StepResult): ...

    @abstractmethod
    def on_log(self, message: str, level: str = "info"): ...


# ──────────────────────────────────────────────────────────
# FACTORY interfaces
# ──────────────────────────────────────────────────────────

class ActionFactory(ABC):
    """Factory: creates the right ActionStrategy for a given action name."""

    @abstractmethod
    def create(self, action_name: str) -> ActionStrategy: ...


class ResolverFactory(ABC):
    """Factory: builds the ordered list of ResolverStrategy instances."""

    @abstractmethod
    def build_cascade(self) -> list[ResolverStrategy]: ...


