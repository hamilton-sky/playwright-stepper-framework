"""
resolvers/shadow_runner.py — Predictive drift detection via shadow strategy comparison.

Shadow Mode: after the real resolver acts on the winning strategy, all other
applicable strategies run in the background and compare their result to the winner.
Divergence between strategies signals locator drift before it breaks.

Pattern: Proxy — wraps ElementResolver, exposes the same interface.
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.interfaces import ResolveResult
from engine.resolvers.element_resolver import CONFIDENCE_MAP

logger = logging.getLogger(__name__)

DRIFT_WARN  = 0.30   # yellow — strategies starting to diverge
DRIFT_ALERT = 0.60   # red    — strong signal of imminent failure

_STRATEGY_WEIGHT = CONFIDENCE_MAP


@dataclass
class ShadowResult:
    strategy:   str
    found:      bool
    agrees:     bool
    confidence: float = 0.0


@dataclass
class DriftRecord:
    step_key:          str
    timestamp:         str
    description:       str
    winner_method:     str
    winner_confidence: float
    shadow_results:    list[ShadowResult]
    drift_score:       float


class DriftLog:
    """Appends drift records to a rolling JSON array (capped at 500 entries)."""

    _MAX_RECORDS  = 500
    _FLUSH_EVERY  = 10   # write to disk every N appends; call flush() to force

    def __init__(self, log_path: Path):
        self._path = log_path
        self._records: list[dict] = []
        self._unflushed = 0
        if log_path.exists():
            try:
                self._records = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("[DriftLog] corrupt log at %s — starting fresh", log_path)

    def append(self, record: DriftRecord) -> None:
        entry = {
            "step_key":          record.step_key,
            "timestamp":         record.timestamp,
            "description":       record.description,
            "winner_method":     record.winner_method,
            "winner_confidence": record.winner_confidence,
            "shadow_results": [
                {
                    "strategy":   r.strategy,
                    "found":      r.found,
                    "agrees":     r.agrees,
                    "confidence": r.confidence,
                }
                for r in record.shadow_results
            ],
            "drift_score": record.drift_score,
        }
        self._records.append(entry)
        if len(self._records) > self._MAX_RECORDS:
            self._records = self._records[-self._MAX_RECORDS:]
        self._unflushed += 1
        if self._unflushed >= self._FLUSH_EVERY:
            self.flush()

    def flush(self) -> None:
        if self._unflushed == 0:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._records, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._unflushed = 0
        except Exception as exc:
            logger.warning("[DriftLog] write failed: %s", exc)

    def latest(self, n: int = 20) -> list[dict]:
        return self._records[-n:]


class ShadowRunner:
    """
    Proxy around ElementResolver.

    On every successful resolution it fires a background task that runs all
    other applicable strategies and compares their result to the winner.
    The main execution path is never blocked — shadow tasks are best-effort.

    Usage:
        base = build_resolver(use_visual_ai)
        shadow = ShadowRunner(base, DefaultResolverFactory().build_cascade(), drift_log)
        # pass shadow wherever an ElementResolver is expected
    """

    def __init__(self, resolver, strategies: list, drift_log: DriftLog):
        self._resolver         = resolver
        self._strategies       = sorted(strategies, key=lambda s: s.priority)
        self._drift_log        = drift_log
        self._last_description = ""
        self._tasks: set       = set()

    # ── ElementResolver interface ─────────────────────────────────────────────

    def set_context_description(self, description: str) -> None:
        self._last_description = description or ""
        self._resolver.set_context_description(description)

    async def resolve(self, page, cfg: dict, step_description: str = "") -> ResolveResult:
        result = await self._resolver.resolve(page, cfg, step_description)
        if result.found and cfg:
            effective_desc = step_description or self._last_description
            task = asyncio.create_task(
                self._safe_shadow_compare(page, cfg, effective_desc, result)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return result

    # ── Shadow task ───────────────────────────────────────────────────────────

    async def _safe_shadow_compare(
        self, page, cfg: dict, step_description: str, winner: ResolveResult
    ) -> None:
        try:
            await self._shadow_compare(page, cfg, step_description, winner)
        except Exception as exc:
            logger.debug("[ShadowRunner] background task error: %s", exc)

    async def _shadow_compare(
        self, page, cfg: dict, step_description: str, winner: ResolveResult
    ) -> None:
        winner_strategy = winner.method.split("+")[0]

        # Only strategies whose cfg key is present and weren't the winner
        applicable = [
            s for s in self._strategies
            if s.name != winner_strategy and s.name in cfg
        ]
        if not applicable:
            return

        tasks = [
            self._run_shadow_strategy(page, cfg, s, winner)
            for s in applicable
        ]
        shadow_results: list[ShadowResult] = await asyncio.gather(*tasks)

        drift_score = _compute_drift(shadow_results)
        record = DriftRecord(
            step_key=_make_key(cfg, step_description),
            timestamp=datetime.now(timezone.utc).isoformat(),
            description=step_description[:120],
            winner_method=winner.method,
            winner_confidence=winner.confidence,
            shadow_results=shadow_results,
            drift_score=round(drift_score, 3),
        )
        self._drift_log.append(record)

        if drift_score >= DRIFT_ALERT:
            logger.warning(
                "🔴 [ShadowRunner] HIGH DRIFT %.0f%% — '%s' (winner: %s). "
                "Locator may break soon.",
                drift_score * 100, step_description[:60], winner.method,
            )
        elif drift_score >= DRIFT_WARN:
            logger.info(
                "🟡 [ShadowRunner] drift %.0f%% — '%s' (winner: %s).",
                drift_score * 100, step_description[:60], winner.method,
            )

    async def _run_shadow_strategy(
        self, page, cfg: dict, strategy, winner: ResolveResult
    ) -> ShadowResult:
        try:
            candidates = await strategy.collect(page, cfg)
            if not candidates:
                return ShadowResult(
                    strategy=strategy.name, found=False, agrees=False,
                    confidence=_STRATEGY_WEIGHT.get(strategy.name, 0.70),
                )
            if len(candidates) != 1:
                # Ambiguous — counts as disagreement
                return ShadowResult(
                    strategy=strategy.name, found=True, agrees=False,
                    confidence=_STRATEGY_WEIGHT.get(strategy.name, 0.70),
                )
            agrees = await _elements_agree(candidates[0], winner.locator)
            return ShadowResult(
                strategy=strategy.name,
                found=True,
                agrees=agrees,
                confidence=_STRATEGY_WEIGHT.get(strategy.name, 0.70),
            )
        except Exception as exc:
            logger.debug("[ShadowRunner] %s error: %s", strategy.name, exc)
            return ShadowResult(
                strategy=strategy.name, found=False, agrees=False,
                confidence=_STRATEGY_WEIGHT.get(strategy.name, 0.70),
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_drift(results: list[ShadowResult]) -> float:
    """Weighted disagreement score in [0, 1]. Higher = more drift."""
    if not results:
        return 0.0
    total  = sum(_STRATEGY_WEIGHT.get(r.strategy, 0.70) for r in results)
    if total == 0:
        return 0.0
    disagree = sum(
        _STRATEGY_WEIGHT.get(r.strategy, 0.70)
        for r in results if not r.agrees
    )
    return disagree / total


async def _elements_agree(loc_a, loc_b) -> bool:
    """Return True if two locators appear to point to the same DOM element."""
    for getter in (
        lambda l: l.inner_text(),
        lambda l: l.get_attribute("aria-label"),
        lambda l: l.get_attribute("id"),
        lambda l: l.get_attribute("placeholder"),
    ):
        try:
            a = (await getter(loc_a) or "").strip()
            b = (await getter(loc_b) or "").strip()
            if a and b:
                return a == b
        except Exception:
            pass
    return False


def _make_key(cfg: dict, description: str) -> str:
    raw = json.dumps(cfg, sort_keys=True) + "|" + (description or "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
