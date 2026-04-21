"""
healer/dom_snapshot.py — Embed-first DOM capture utility for AiHealer.

Walks an embedding-driven decision tree to keep the AI prompt as small as
possible. The cheapest outcome (Strategy 1, unique high-confidence match)
needs zero AI tokens — we synthesise a healed cfg from the element's own
attributes. The most expensive (full ARIA snapshot) is only reached when no
candidate scores above 0.50.

  ≥ 0.85, unique     → embed_direct      (no AI call, healed_cfg ready)
  ≥ 0.85, ambiguous  → embed_candidates  (~20-40 tokens)
  0.50-0.85          → scoped DOM area   (~40-150 tokens)
  < 0.50             → aria snapshot     (~200-500 tokens)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from engine.interfaces import StepConfig
from engine.healer.interfaces import DomPayload
from engine.resolvers.strategies import SemanticResolver

logger = logging.getLogger(__name__)

_HIGH_THRESHOLD = 0.85
_LOW_THRESHOLD = 0.50
_TOP_N = 5
_INTERACTIVE_SELECTOR = (
    "button,a,input,select,textarea,[role],[aria-label]"
)
_ELEMENT_QUERY_JS = """() =>
  [...document.querySelectorAll('button,a,input,select,textarea,[role],[aria-label]')].map(el => ({
    tag: el.tagName,
    text: el.textContent?.trim().slice(0,80),
    role: el.getAttribute('role'),
    aria: el.getAttribute('aria-label'),
    id: el.id,
    placeholder: el.getAttribute('placeholder')
  }))
"""


def _estimate_tokens(text: str) -> int:
    """Rough token count — 1 token per ~4 characters."""
    return max(1, len(text) // 4) if text else 0


class DOMSnapshotCascade:
    """Embed-first cascade. One public method: capture(page, step) -> DomPayload."""

    _semantic: SemanticResolver | None = None

    @classmethod
    def _get_semantic(cls) -> SemanticResolver:
        if cls._semantic is None:
            cls._semantic = SemanticResolver()
        return cls._semantic

    # ── Public API ───────────────────────────────────────────────────────────

    @classmethod
    async def capture(cls, page, step: StepConfig) -> DomPayload:
        query = cls._build_query(step)
        elements = await cls._collect_elements(page)

        if not elements:
            return await cls._aria_fallback(page, reason="no interactive elements")

        scored = cls._score_elements(query, elements)
        scored.sort(key=lambda x: x[1], reverse=True)

        top_score = scored[0][1] if scored else 0.0

        if top_score >= _HIGH_THRESHOLD:
            high = [s for s in scored if s[1] >= _HIGH_THRESHOLD]
            if len(high) == 1:
                element = high[0][0]
                return DomPayload(
                    strategy_used="embed_direct",
                    content="",
                    healed_cfg=cls._element_to_cfg(element),
                    token_estimate=0,
                )
            return cls._candidates_payload(high, "embed_candidates")

        if top_score >= _LOW_THRESHOLD:
            best_element, best_score = scored[0]
            scoped_html = await cls._scoped_html(page, best_element)
            mid = [s for s in scored if s[1] >= _LOW_THRESHOLD]
            content_obj: dict[str, Any] = {
                "best_match": cls._element_to_cfg(best_element),
                "best_match_score": round(best_score, 3),
                "candidates": [cls._element_to_cfg(e) for e, _ in mid[:_TOP_N]],
            }
            if scoped_html:
                content_obj["scoped_html"] = scoped_html[:4000]
            content = json.dumps(content_obj, ensure_ascii=False)
            return DomPayload(
                strategy_used="scoped",
                content=content,
                healed_cfg=None,
                token_estimate=_estimate_tokens(content),
            )

        return await cls._aria_fallback(page, reason=f"top score {top_score:.2f} < {_LOW_THRESHOLD}")

    # ── Query construction ────────────────────────────────────────────────────

    @staticmethod
    def _build_query(step: StepConfig) -> str:
        parts: list[str] = []
        if step.description:
            parts.append(step.description)
        for v in (step.extra or {}).values():
            if isinstance(v, str) and v:
                parts.append(v)
        query = " ".join(parts).strip()

        if len(query) < 15:
            tail = " ".join(step.action.replace("_", " ").split()[-3:]) if step.action else ""
            extras = " ".join(str(v) for v in (step.extra or {}).values() if v)
            query = " ".join(p for p in (query, tail, extras) if p).strip()
        return query

    # ── Element collection ────────────────────────────────────────────────────

    @staticmethod
    async def _collect_elements(page) -> list[dict]:
        try:
            raw = await page.evaluate(_ELEMENT_QUERY_JS)
        except Exception as e:
            logger.debug(f"[DOMSnapshotCascade] page.evaluate failed: {e}")
            return []
        return [el for el in (raw or []) if isinstance(el, dict)]

    # ── Scoring ───────────────────────────────────────────────────────────────

    @classmethod
    def _score_elements(cls, query: str, elements: list[dict]) -> list[tuple[dict, float]]:
        if not query:
            return [(el, 0.0) for el in elements]
        sem = cls._get_semantic()
        scored: list[tuple[dict, float]] = []
        for el in elements:
            desc = cls._describe_element(el)
            if not desc:
                continue
            scored.append((el, sem.score(query, desc)))
        return scored

    @staticmethod
    def _describe_element(el: dict) -> str:
        return " ".join(filter(None, [
            (el.get("text") or "").strip(),
            el.get("aria") or "",
            el.get("placeholder") or "",
            el.get("role") or "",
        ])).strip()

    # ── Cfg synthesis ─────────────────────────────────────────────────────────

    @staticmethod
    def _element_to_cfg(el: dict) -> dict:
        cfg: dict[str, Any] = {"priority": 0}
        role = (el.get("role") or "").strip()
        text = (el.get("text") or "").strip()
        aria = (el.get("aria") or "").strip()
        placeholder = (el.get("placeholder") or "").strip()
        elem_id = (el.get("id") or "").strip()
        tag = (el.get("tag") or "").lower()

        if role and (aria or text):
            cfg["role"] = role
            cfg["name"] = aria or text
        elif aria:
            cfg["label"] = aria
        elif placeholder:
            cfg["placeholder"] = placeholder
        elif text:
            cfg["text"] = text
        elif elem_id:
            cfg["id"] = elem_id
        elif tag:
            cfg["css"] = tag
        return cfg

    @classmethod
    def _candidates_payload(cls, scored: list[tuple[dict, float]], strategy: str) -> DomPayload:
        top = scored[:_TOP_N]
        candidates = [
            {**cls._element_to_cfg(el), "_score": round(score, 3)}
            for el, score in top
        ]
        content = json.dumps({"candidates": candidates}, ensure_ascii=False)
        return DomPayload(
            strategy_used=strategy,
            content=content,
            healed_cfg=None,
            token_estimate=_estimate_tokens(content),
        )

    # ── Scoped DOM area ───────────────────────────────────────────────────────

    @staticmethod
    async def _scoped_html(page, element: dict) -> str:
        selector = None
        if element.get("id"):
            selector = f"#{element['id']}"
        elif element.get("aria"):
            aria = element["aria"].replace('"', '\\"')
            selector = f'[aria-label="{aria}"]'
        if not selector:
            return ""
        try:
            return await page.evaluate(
                "(sel) => document.querySelector(sel)?.closest('form,main,section,nav,dialog')?.outerHTML || ''",
                selector,
            )
        except Exception as e:
            logger.debug(f"[DOMSnapshotCascade] scoped html fetch failed: {e}")
            return ""

    # ── ARIA fallback ─────────────────────────────────────────────────────────

    @staticmethod
    async def _aria_fallback(page, reason: str) -> DomPayload:
        # page.accessibility was removed in Playwright ≥1.40; use a JS walk instead.
        _DOM_WALK_JS = """() => {
            const walk = (el, depth) => {
                if (depth > 4 || !el) return null;
                return {
                    tag:  el.tagName?.toLowerCase(),
                    role: el.getAttribute?.('role'),
                    aria: el.getAttribute?.('aria-label'),
                    text: el.textContent?.trim().slice(0, 80),
                    id:   el.id || undefined,
                    ph:   el.getAttribute?.('placeholder'),
                    children: [...(el.children || [])]
                        .map(c => walk(c, depth + 1)).filter(Boolean).slice(0, 20)
                };
            };
            return walk(document.body, 0);
        }"""
        snapshot = None
        try:
            snapshot = await page.evaluate(_DOM_WALK_JS)
        except Exception as e:
            logger.warning(f"[DOMSnapshotCascade] DOM walk failed: {e}")

        content = json.dumps(snapshot, ensure_ascii=False) if snapshot else ""
        logger.debug(f"[DOMSnapshotCascade] aria fallback ({reason})")
        return DomPayload(
            strategy_used="aria",
            content=content,
            healed_cfg=None,
            token_estimate=_estimate_tokens(content),
        )
