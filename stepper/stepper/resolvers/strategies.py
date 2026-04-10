"""
resolvers/strategies.py — Concrete ResolverStrategy implementations.

Pattern: Strategy + Chain of Responsibility
  Each class knows ONE way to find elements.
  ElementResolver tries them in priority order.

OCP: Add a new strategy without touching ElementResolver or any other file.
SRP: Each strategy handles exactly one find method.

Priority order mirrors Playwright's official locator recommendation
(https://playwright.dev/docs/locators#quick-guide):
  10 RoleResolver        — getByRole()        Playwright #1
  20 LabelResolver       — getByLabel()       Playwright #2
  30 PlaceholderResolver — getByPlaceholder() Playwright #3
  40 TextResolver        — getByText()        Playwright #4
  50 IdResolver          — #id selector       Playwright #5 (closest to testId)
  60 CssResolver         — CSS selector       implementation detail, fragile
  70 XPathResolver       — XPath              most brittle, DOM-structure dependent
  80 SemanticResolver    (used only via score(), not in cascade)
  90 VisualAIResolver    (fallback, not in cascade list)

  DescriptionFallbackResolver is NOT in the cascade.
  It is invoked directly by ElementResolver when element cfg has no recognized keys.
"""

from __future__ import annotations
import base64
import json
import logging
from typing import Optional

from stepper.interfaces import ResolverStrategy, CONFIDENCE_DESCRIPTION

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# PHASE 1 — Deterministic resolvers
# ──────────────────────────────────────────────────────────

class TextResolver(ResolverStrategy):
    """Find by visible text content. Playwright priority #4."""
    priority = 40
    name = "text"

    async def collect(self, page, cfg: dict) -> list:
        text = cfg.get("text", "")
        if not text:
            return []
        try:
            # exact=True by default — avoids matching every element that
            # *contains* the text (e.g. "Want to Read" matching nav/footer too)
            exact = cfg.get("exact", True)
            loc = page.get_by_text(text, exact=exact)
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[TextResolver] {e}")
            return []


class RoleResolver(ResolverStrategy):
    """Find by ARIA role, optionally narrowed by accessible name. Playwright priority #1."""
    priority = 10
    name = "role"

    async def collect(self, page, cfg: dict) -> list:
        role = cfg.get("role", "")
        if not role:
            return []
        name = cfg.get("name") or cfg.get("label") or cfg.get("text", "")
        exact = cfg.get("exact", True)
        try:
            kwargs = {"name": name, "exact": exact} if name else {}
            loc = page.get_by_role(role, **kwargs)
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[RoleResolver] {e}")
            return []


class PlaceholderResolver(ResolverStrategy):
    """Find by input placeholder text. Playwright priority #3."""
    priority = 30
    name = "placeholder"

    async def collect(self, page, cfg: dict) -> list:
        ph = cfg.get("placeholder", "")
        if not ph:
            return []
        try:
            loc = page.get_by_placeholder(ph)
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[PlaceholderResolver] {e}")
            return []


class IdResolver(ResolverStrategy):
    """Find by element id attribute. Playwright priority #5 (closest to testId)."""
    priority = 50
    name = "id"

    async def collect(self, page, cfg: dict) -> list:
        element_id = cfg.get("id", "")
        if not element_id:
            return []
        try:
            loc = page.locator(f"#{element_id}")
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[IdResolver] {e}")
            return []


class CssResolver(ResolverStrategy):
    """Find by CSS selector. Implementation detail — fragile on DOM changes."""
    priority = 60
    name = "css"

    async def collect(self, page, cfg: dict) -> list:
        css = cfg.get("css", "")
        if not css:
            return []
        try:
            loc = page.locator(css)
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[CssResolver] {e}")
            return []


class XPathResolver(ResolverStrategy):
    """Find by XPath expression. Most brittle — depends on DOM structure."""
    priority = 70
    name = "xpath"

    async def collect(self, page, cfg: dict) -> list:
        xpath = cfg.get("xpath", "")
        if not xpath:
            return []
        try:
            loc = page.locator(f"xpath={xpath}")
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[XPathResolver] {e}")
            return []


class LabelResolver(ResolverStrategy):
    """Find form inputs by their associated label text. Playwright priority #2."""
    priority = 20
    name = "label"

    async def collect(self, page, cfg: dict) -> list:
        label = cfg.get("label", "")
        if not label:
            return []
        try:
            loc = page.get_by_label(label)
            count = await loc.count()
            return [loc.nth(i) for i in range(count)] if count else []
        except Exception as e:
            logger.debug(f"[LabelResolver] {e}")
            return []


# ──────────────────────────────────────────────────────────
# PHASE 2 — Semantic resolver (used via score(), not collect())
# ──────────────────────────────────────────────────────────

class SemanticResolver(ResolverStrategy):
    """
    Computes semantic similarity between a query and a candidate description.
    Used by ElementResolver._semantic_filter(), not via the collect() cascade.

    Implementation: sentence-transformers cosine similarity when available,
    falls back to Jaccard word overlap so the system always works offline.
    OCP: swap the embedding backend by subclassing and overriding score().
    """
    priority = 80
    name = "semantic"

    def __init__(self):
        self._model = None
        self._use_embeddings = False
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
            import pathlib
            _model_path = pathlib.Path(__file__).parents[2] / "models" / "all-MiniLM-L6-v2"
            self._model = SentenceTransformer(str(_model_path))
            self._np = np
            self._use_embeddings = True
            logger.info("[SemanticResolver] sentence-transformers loaded from %s", _model_path)
        except ImportError:
            logger.debug("[SemanticResolver] sentence-transformers not installed — using Jaccard fallback")
        except Exception as exc:
            logger.warning("[SemanticResolver] could not load sentence-transformers model (%s) — using Jaccard fallback", exc)

    def score(self, query: str, text: str) -> float:
        """
        Returns a [0, 1] similarity score between query and text.
        Uses cosine similarity over sentence embeddings when available,
        otherwise Jaccard word overlap.
        """
        if not query or not text:
            return 0.0

        if self._use_embeddings:
            return self._cosine_score(query, text)
        return self._jaccard_score(query, text)

    def _cosine_score(self, query: str, text: str) -> float:
        try:
            vecs = self._model.encode([query, text])
            q, t = vecs[0], vecs[1]
            denom = (self._np.linalg.norm(q) * self._np.linalg.norm(t))
            if denom == 0:
                return 0.0
            return float(self._np.dot(q, t) / denom)
        except Exception as e:
            logger.debug(f"[SemanticResolver] embedding error: {e} — falling back to Jaccard")
            return self._jaccard_score(query, text)

    def _jaccard_score(self, query: str, text: str) -> float:
        q_tokens = set(query.lower().split())
        t_tokens = set(text.lower().split())
        if not q_tokens or not t_tokens:
            return 0.0
        intersection = q_tokens & t_tokens
        union = q_tokens | t_tokens
        return len(intersection) / len(union)

    async def collect(self, page, cfg: dict) -> list:
        # SemanticResolver is not a standalone finder — it only scores.
        return []


# ──────────────────────────────────────────────────────────
# PHASE 2.5 — Description Fallback (zero-selector mode)
# ──────────────────────────────────────────────────────────

class DescriptionFallbackResolver:
    """
    Fires when the step has NO element selector keys (no text/css/id/role/etc).
    Collects all interactive elements on the page, scores each against
    step.description using SemanticResolver, returns the best match.

    This enables zero-selector automation:
      { "action": "click", "description": "Add this book to my reading list" }
      — no "element" key needed at all.

    NOT in the strategy cascade (collect() interface lacks step_description).
    Called directly by ElementResolver._description_fallback().

    Confidence = similarity_score × 0.9  (caps at 0.9 to stay below
    deterministic resolvers with known-good selectors).

    Threshold: similarity >= 0.40 to act; below that → not-found.
    """

    # Playwright selector for all interactive / meaningful elements
    INTERACTIVE_SELECTOR = (
        "button, a[href], input, select, textarea, "
        "[role='button'], [role='link'], [role='menuitem'], "
        "[role='tab'], [role='checkbox'], [role='radio']"
    )
    MIN_SIMILARITY = CONFIDENCE_DESCRIPTION  # from stepper.interfaces — single source of truth
    MAX_CANDIDATES = 60  # cap to avoid huge DOMs being slow

    def __init__(self):
        self._semantic = SemanticResolver()

    async def find(self, page, description: str) -> tuple[object | None, float]:
        """
        Returns (locator, confidence) or (None, 0.0) if nothing matches.
        """
        if not description:
            return None, 0.0

        try:
            all_locs = await page.locator(self.INTERACTIVE_SELECTOR).all()
        except Exception as e:
            logger.debug(f"[DescriptionFallback] locator error: {e}")
            return None, 0.0

        candidates = all_locs[:self.MAX_CANDIDATES]
        if not candidates:
            return None, 0.0

        scored: list[tuple[object, str, float]] = []
        for loc in candidates:
            element_desc = await self._describe(loc)
            if not element_desc:
                continue
            score = self._semantic.score(description, element_desc)
            scored.append((loc, element_desc, score))

        if not scored:
            return None, 0.0

        scored.sort(key=lambda x: x[2], reverse=True)
        best_loc, best_desc, best_score = scored[0]

        logger.debug(
            f"[DescriptionFallback] top match: '{best_desc[:60]}' "
            f"score={best_score:.2f}"
        )

        if best_score < self.MIN_SIMILARITY:
            logger.warning(
                f"[DescriptionFallback] best score {best_score:.2f} < "
                f"{self.MIN_SIMILARITY} threshold — not-found"
            )
            return None, 0.0

        confidence = round(best_score * 0.9, 3)
        logger.info(
            f"✓ [description-fallback] '{best_desc[:50]}' "
            f"similarity={best_score:.0%} → confidence={confidence:.0%}"
        )
        return best_loc, confidence

    @staticmethod
    async def _describe(loc) -> str:
        """Build a human-readable description of an element for scoring."""
        try:
            tag         = await loc.evaluate("el => el.tagName.toLowerCase()")
            text        = (await loc.inner_text()).strip()[:80]
            aria_label  = await loc.get_attribute("aria-label") or ""
            title       = await loc.get_attribute("title") or ""
            placeholder = await loc.get_attribute("placeholder") or ""
            role        = await loc.get_attribute("role") or ""
            parts = filter(None, [tag, role, aria_label, title, placeholder, text])
            return " ".join(parts).strip()
        except Exception:
            return ""


# ──────────────────────────────────────────────────────────
# PHASE 3 — Visual AI resolver (last resort)
# ──────────────────────────────────────────────────────────

class VisualAIResolver(ResolverStrategy):
    """
    Last-resort resolver: takes a full-page screenshot and asks Claude
    to identify the element's CSS selector via vision.

    Returns a list of (locator, confidence) tuples.
    ElementResolver._visual_fallback() unpacks these.
    """
    priority = 90
    name = "visual-ai"

    def __init__(self, ai_client=None):
        self._ai = ai_client

    async def collect(self, page, cfg: dict) -> list[tuple]:
        """
        Returns list of (locator, confidence) tuples, or [] if unavailable.
        Note: returns tuples, not plain Locators, to carry confidence.
        """
        if not self._ai:
            logger.debug("[VisualAIResolver] no AI client — skipping")
            return []

        step_description = cfg.get("_step_description", str(cfg))

        try:
            screenshot_bytes = await page.screenshot(full_page=False)
            b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

            response = self._ai.messages.create(
                model="claude-opus-4-6",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f'Find element for: "{step_description}"\n'
                                'Return ONLY JSON: {"selector": ".css-selector", "confidence": 0.85}'
                            ),
                        },
                    ],
                }]
            )

            data = json.loads(response.content[0].text.strip())
            selector = data.get("selector", "")
            confidence = float(data.get("confidence", 0.5))

            if not selector:
                return []

            loc = page.locator(selector)
            count = await loc.count()
            if count == 0:
                logger.warning(f"[VisualAIResolver] AI selector '{selector}' matched 0 elements")
                return []

            logger.info(f"[VisualAIResolver] found '{selector}' (confidence {confidence:.0%})")
            return [(loc.first, confidence)]

        except Exception as e:
            logger.error(f"[VisualAIResolver] {e}")
            return []
