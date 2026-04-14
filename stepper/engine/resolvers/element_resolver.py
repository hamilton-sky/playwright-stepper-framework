"""
resolvers/element_resolver.py — Cascade orchestrator.

Pattern: Strategy + Chain of Responsibility
  - Holds an ordered list of ResolverStrategy objects
  - Tries each in priority order
  - On multiple matches → SemanticResolver filters → AI picks if still ambiguous
  - On total failure → VisualAIResolver last resort

OCP: Add a new resolver strategy without touching this file.
SRP: Only decides WHICH element to act on, never performs the action itself.
"""

from __future__ import annotations
import logging
from typing import Optional

from engine.interfaces import (
    ResolveResult, ResolverFactory,
    CONFIDENCE_SEMANTIC, CONFIDENCE_AI_PICK,
)
from engine.resolvers.strategies import (
    SemanticResolver, VisualAIResolver, DescriptionFallbackResolver, KeywordFuzzyResolver,
)
from engine.resolvers.ai_pick_resolver import AIPickResolver

logger = logging.getLogger(__name__)

# Aliases for readability within this module (values come from interfaces.py)
SEMANTIC_THRESHOLD = CONFIDENCE_SEMANTIC
AI_PICK_THRESHOLD  = CONFIDENCE_AI_PICK
CONFIDENCE_MAP = {
    # Mirrors Playwright's official locator priority (highest = tried first, most resilient)
    "role":        0.95,   # Playwright #1 — role + accessible name, survives redesigns
    "label":       0.93,   # Playwright #2 — associated <label>, semantically stable
    "placeholder": 0.90,   # Playwright #3 — input placeholder text
    "text":        0.85,   # Playwright #4 — visible text (can match non-interactive elements)
    "id":          0.82,   # Playwright #5 — unique id (fragile if ids are generated)
    "css":         0.75,   # implementation detail — breaks on class/DOM refactors
    "xpath":       0.70,   # most brittle — encodes full DOM structure
    "semantic":              None,   # uses actual similarity score
    "visual-ai":             None,   # uses score from AI response
    "keyword-fuzzy":         0.85,   # Strategy B — single keyword text match
    "accessibility-semantic": 0.87,  # Strategy A — accessibility snapshot + MiniLM unique match
}


class ElementResolver:
    """
    Cascade resolver.

    Phase 1 (deterministic) → Phase 2 (semantic) → Phase 3 (visual AI)

    Usage:
        resolver = ElementResolver(factory.build_cascade(), ai_client)
        result   = await resolver.resolve(page, element_cfg, step_description)
    """

    # Keys that indicate a concrete element selector is provided
    _SELECTOR_KEYS = frozenset({"text", "role", "placeholder", "id", "css", "xpath", "label"})

    def __init__(self, strategies: list, ai_client=None, *, use_visual_ai: bool = False):
        # Sort by priority — lowest first
        self._strategies    = sorted(strategies, key=lambda s: s.priority)
        self._ai            = ai_client
        self._semantic      = SemanticResolver()
        self._visual        = VisualAIResolver(ai_client)
        self._desc_fallback = DescriptionFallbackResolver()
        self._keyword_fuzzy = KeywordFuzzyResolver()
        self._use_visual_ai = use_visual_ai
        self._ai_pick_resolver = AIPickResolver()   # Groq → Gemini → Claude
        self._context_description: str = ""        # set by StepRunner before each action

    def set_context_description(self, description: str) -> None:
        """
        Called by StepRunner before each action executes.
        Provides the step description as fallback context for resolver.resolve()
        calls that don't pass an explicit step_description — i.e. every POM
        method call going through _resolve_and_click_any / _resolve_and_fill_any.
        """
        self._context_description = description or ""

    async def resolve(
        self,
        page,
        cfg: dict,
        step_description: str = "",
    ) -> ResolveResult:
        # Use context description as fallback when caller doesn't pass one.
        # StepRunner.run() calls set_context_description(step.description) before
        # every action, so POM methods that call resolve() without a description
        # still get the step's semantic context for fallback resolution.
        step_description = step_description or self._context_description

        # Zero-selector mode: no recognized element keys → B → A → AI pick
        if not cfg or not any(k in cfg for k in self._SELECTOR_KEYS):
            if step_description:
                logger.info(
                    f"[ElementResolver] no element keys in cfg — "
                    f"zero-selector path: '{step_description[:60]}'"
                )
                return await self._zero_selector_path(page, step_description)
            logger.warning("[ElementResolver] no cfg and no description → not-found")
            return ResolveResult(found=False, confidence=0.0, method="not-found")

        for strategy in self._strategies:
            candidates = await strategy.collect(page, cfg)
            if not candidates:
                continue

            if len(candidates) == 1:
                conf = CONFIDENCE_MAP.get(strategy.name, 0.80)
                logger.info(f"✓ [{strategy.name}] found 1 element — confidence {conf:.0%}")
                return ResolveResult(
                    found=True, locator=candidates[0],
                    confidence=conf, method=strategy.name
                )

            # Multiple matches → try semantic filter
            logger.debug(f"[{strategy.name}] {len(candidates)} candidates → semantic filter")
            result = await self._semantic_filter(
                candidates, step_description, strategy.name
            )
            if result.found:
                return result

        # All deterministic strategies failed → fall through to zero-selector path
        # (B keyword fuzzy → A accessibility semantic → AI pick → visual AI)
        # This handles stale selectors, renamed ids, DOM refactors etc.
        if step_description:
            logger.warning(
                "Deterministic cascade failed — falling through to "
                f"zero-selector path: '{step_description[:60]}'"
            )
            return await self._zero_selector_path(page, step_description)

        logger.warning("Deterministic cascade failed and no description → visual AI")
        return await self._visual_fallback(page, cfg, step_description)

    # ── Zero-selector path (B → A → AI pick) ─────────────────────────────────

    async def _zero_selector_path(self, page, step_description: str) -> "ResolveResult":
        """
        Two-stage pipeline for steps with no element cfg keys:

        B (KeywordFuzzyResolver, ~5 ms)
          Extracts content keywords from step description, runs get_by_text()
          for each.  Exactly 1 unique text match → act at 85% confidence.
          0 or multiple → fall through to A.

        A (DescriptionFallbackResolver, ~50 ms)
          Collects interactive ARIA nodes via page.accessibility.snapshot(),
          scores each node's composite string against step_description using
          MiniLM.  Returns top-3 candidates above the 0.40 threshold.
            1 candidate  → act at score × 0.9 confidence
            2–3 candidates → _ai_pick() disambiguation (Groq → Gemini → Claude)
            0 candidates → visual AI last resort
        """
        # ── B: Keyword fuzzy — fast gate ──────────────────────────────────────
        b_candidates = await self._keyword_fuzzy.find(page, step_description)
        if len(b_candidates) == 1:
            logger.info("✓ [keyword-fuzzy] single match → confidence 85%")
            return ResolveResult(
                found=True, locator=b_candidates[0],
                confidence=CONFIDENCE_MAP["keyword-fuzzy"],
                method="keyword-fuzzy",
            )
        if b_candidates:
            logger.debug(
                f"[keyword-fuzzy] {len(b_candidates)} candidates → "
                "falling through to accessibility-semantic"
            )

        # ── A: Accessibility snapshot + semantic scoring ───────────────────────
        shortlist = await self._desc_fallback.find_candidates(page, step_description)

        if not shortlist:
            logger.warning(
                "[DescriptionFallback] no candidates above threshold → visual AI"
            )
            return await self._visual_fallback(page, {}, step_description)

        if len(shortlist) == 1:
            loc, desc, score = shortlist[0]
            confidence = round(score * 0.9, 3)
            logger.info(
                f"✓ [accessibility-semantic] '{desc[:50]}' "
                f"similarity={score:.0%} → confidence={confidence:.0%}"
            )
            return ResolveResult(
                found=True, locator=loc,
                confidence=confidence,
                method="accessibility-semantic",
            )

        # Multiple candidates — AI picks the best one
        logger.debug(
            f"[accessibility-semantic] {len(shortlist)} candidates → AI pick"
        )
        return await self._ai_pick(shortlist, step_description, "accessibility-semantic")

    # ── Semantic Filter ────────────────────────────────────────────────────────

    async def _semantic_filter(
        self,
        candidates: list,
        step_description: str,
        method: str,
    ) -> ResolveResult:

        if not step_description:
            # No description — just take first candidate
            return ResolveResult(
                found=True, locator=candidates[0],
                confidence=0.70, method=f"{method}+first"
            )

        shortlist = []
        for loc in candidates:
            desc = await self._describe_locator(loc)
            score = self._semantic.score(step_description, desc)
            if score >= SEMANTIC_THRESHOLD:
                shortlist.append((loc, desc, score))

        shortlist.sort(key=lambda x: x[2], reverse=True)

        if not shortlist:
            return ResolveResult(found=False, method=f"{method}+semantic-miss")

        if len(shortlist) == 1:
            loc, _, score = shortlist[0]
            return ResolveResult(
                found=True, locator=loc,
                confidence=score, method=f"{method}+semantic"
            )

        # Still ambiguous — AI pick
        return await self._ai_pick(shortlist, step_description, method)

    # ── AI Pick ───────────────────────────────────────────────────────────────

    async def _ai_pick(self, shortlist, step_description, method) -> ResolveResult:
        """
        Disambiguate multiple candidates via AIPickResolver.
        Provider chain: Groq (free) → Gemini (cheap) → Claude (powerful).
        Falls back to top semantic match if all providers fail.
        """
        options = "\n".join([
            f"{i+1}. \"{desc}\" (similarity: {score:.2f})"
            for i, (_, desc, score) in enumerate(shortlist)
        ])

        result = await self._ai_pick_resolver.pick(
            candidates_text=options,
            step_description=step_description,
            n_candidates=len(shortlist),
        )

        if result is not None:
            idx, conf = result
            if conf < AI_PICK_THRESHOLD:
                return ResolveResult(found=False, method=f"{method}+ai-uncertain")
            loc, _, _ = shortlist[idx]
            return ResolveResult(
                found=True, locator=loc,
                confidence=conf, method=f"{method}+semantic+ai"
            )

        # All AI backends failed — fall back to top semantic match
        logger.warning("[ai_pick] all backends failed — using top semantic match")
        loc, _, score = shortlist[0]
        return ResolveResult(found=True, locator=loc, confidence=score,
                             method=f"{method}+semantic")

    # ── Visual Fallback ───────────────────────────────────────────────────────

    async def _visual_fallback(self, page, cfg, step_description) -> ResolveResult:
        if not self._use_visual_ai:
            logger.warning("Visual AI disabled — returning not-found")
            return ResolveResult(found=False, confidence=0.0, method="not-found")
        candidates = await self._visual.collect(page, cfg)
        if candidates:
            loc, conf = candidates[0]
            return ResolveResult(found=True, locator=loc, confidence=conf, method="visual-ai")
        return ResolveResult(found=False, confidence=0.0, method="not-found")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _describe_locator(loc) -> str:
        try:
            text  = (await loc.inner_text()).strip()[:80]
            role  = await loc.get_attribute("role") or ""
            label = await loc.get_attribute("aria-label") or ""
            ph    = await loc.get_attribute("placeholder") or ""
            return " ".join(filter(None, [role, label, ph, text])).strip()
        except Exception:
            return ""


# ── Default Factory ───────────────────────────────────────────────────────────

class DefaultResolverFactory(ResolverFactory):
    """
    Builds the Phase 1 deterministic cascade.
    Phase 2 (semantic) and Phase 3 (visual) are handled internally by ElementResolver.
    To add a new strategy: add it here. Zero changes elsewhere. (OCP)
    """

    def build_cascade(self):
        from engine.resolvers.strategies import (
            TextResolver, RoleResolver, PlaceholderResolver,
            IdResolver, CssResolver, XPathResolver, LabelResolver
        )
        return [
            TextResolver(),
            RoleResolver(),
            PlaceholderResolver(),
            IdResolver(),
            CssResolver(),
            XPathResolver(),
            LabelResolver(),
        ]
