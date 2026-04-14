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
import re
from typing import Optional

from engine.interfaces import ResolverStrategy, CONFIDENCE_DESCRIPTION

# Words that carry no element-matching signal — excluded from keyword extraction
_STOPWORDS = frozenset({
    # Articles / prepositions — never appear as button text
    "the", "a", "an", "to", "of", "and", "or", "in", "on", "at",
    "by", "for", "is", "it", "this", "that", "my", "your", "their",
    "its", "with", "from", "into",
    # Generic automation verbs — describe the *action*, not the element label.
    # NOTE: "add" is intentionally excluded — many buttons read "Add to Cart",
    # "Add to Reading List", etc., so it carries real matching signal.
    "click", "press", "tap", "choose", "enter", "type",
    "fill", "find", "open", "go", "navigate", "make", "sure",
    # UI chrome words — too broad to discriminate
    "page", "button", "link", "field", "form",
})

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
# PHASE 1.5 — Keyword fuzzy pre-filter (Strategy B)
# ──────────────────────────────────────────────────────────

class KeywordFuzzyResolver:
    """
    Strategy B: fast keyword pre-filter for zero-selector mode.

    Extracts content words (≥4 chars, not stopwords) from the step description,
    then calls page.get_by_text(keyword, exact=False) for each keyword.
    Returns unique Playwright locators whose visible text contains any keyword.

    Used as a cheap gate before AccessibilitySemanticResolver (Strategy A).
    Exactly 1 unique match → act immediately at 85% confidence.
    0 or 2+ matches → fall through to Strategy A.
    """

    MIN_WORD_LEN = 4

    async def find(self, page, description: str) -> list:
        keywords = self._extract_keywords(description)
        if not keywords:
            return []

        seen_inner: set[str] = set()
        candidates: list = []

        for keyword in keywords:
            try:
                loc = page.get_by_text(keyword, exact=False)
                count = await loc.count()
                for i in range(count):
                    item = loc.nth(i)
                    try:
                        inner = (await item.inner_text()).strip()[:120]
                        if inner and inner not in seen_inner:
                            seen_inner.add(inner)
                            candidates.append(item)
                    except Exception:
                        pass
            except Exception:
                pass

        return candidates

    def _extract_keywords(self, description: str) -> list[str]:
        words = re.findall(rf'\b[a-zA-Z]{{{self.MIN_WORD_LEN},}}\b', description)
        return [w for w in words if w.lower() not in _STOPWORDS]


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
# PHASE 2.5 — Description Fallback / Strategy A (zero-selector mode)
# ──────────────────────────────────────────────────────────

class DescriptionFallbackResolver:
    """
    Strategy A: accessibility-snapshot semantic search.

    Fires when the step has NO element selector keys (no text/css/id/role/etc).
    Uses page.accessibility.snapshot() to collect all interactive ARIA nodes,
    scores each node's composite description against the step description using
    MiniLM embeddings (or Jaccard fallback), and returns the top-k candidates
    above the similarity threshold.

    Enables zero-selector automation:
      { "action": "click", "description": "Add this book to my reading list" }
      — no "element" key needed at all.

    Why accessibility snapshot over DOM scraping:
      - ARIA tree is already semantically structured (role + name extracted)
      - No layout noise (display:none elements excluded automatically)
      - Playwright resolves accessible names including aria-label, aria-labelledby

    find_candidates() returns list[(locator, desc, score)] — caller decides
    whether to act (1 result) or forward to AI pick (multiple results).
    Confidence is capped at score × 0.9 to stay below deterministic resolvers.

    Threshold: similarity >= 0.40; above that → included in candidates.
    TOP_K = 3 candidates returned at most.
    """

    # ARIA roles that represent interactive / meaningful elements
    INTERACTIVE_ROLES = frozenset({
        "button", "link", "textbox", "checkbox", "radio", "combobox",
        "option", "listbox", "menuitem", "menuitemcheckbox", "menuitemradio",
        "searchbox", "slider", "spinbutton", "switch", "tab", "treeitem",
    })
    MIN_SIMILARITY = CONFIDENCE_DESCRIPTION  # single source of truth in interfaces.py
    TOP_K = 3

    def __init__(self):
        self._semantic = SemanticResolver()

    async def find_candidates(
        self, page, description: str
    ) -> list[tuple]:
        """
        Returns list of (locator, desc, score) sorted by score descending.
        Empty list if nothing meets the similarity threshold.
        """
        if not description:
            return []

        try:
            snapshot = await page.accessibility.snapshot()
        except Exception as e:
            logger.debug(f"[DescriptionFallback] accessibility.snapshot() error: {e}")
            return []

        if not snapshot:
            return []

        nodes = self._flatten_snapshot(snapshot)
        if not nodes:
            return []

        scored: list[tuple] = []
        for node in nodes:
            node_desc = self._describe_node(node)
            if not node_desc:
                continue
            score = self._semantic.score(description, node_desc)
            if score >= self.MIN_SIMILARITY:
                loc = await self._node_to_locator(page, node)
                if loc is not None:
                    scored.append((loc, node_desc, score))

        scored.sort(key=lambda x: x[2], reverse=True)
        top = scored[:self.TOP_K]

        if top:
            logger.debug(
                f"[DescriptionFallback] top-{len(top)} candidates: "
                + ", ".join(f"'{d[:40]}' {s:.2f}" for _, d, s in top)
            )
        return top

    def _flatten_snapshot(self, node: dict, result: list | None = None) -> list[dict]:
        """DFS traversal — collect all interactive nodes by ARIA role."""
        if result is None:
            result = []
        if not isinstance(node, dict):
            return result

        role = (node.get("role") or "").lower()
        name = (node.get("name") or "").strip()
        if role in self.INTERACTIVE_ROLES and name:
            result.append(node)

        for child in node.get("children") or []:
            self._flatten_snapshot(child, result)

        return result

    @staticmethod
    def _describe_node(node: dict) -> str:
        """Build a scoring-ready description from an accessibility tree node."""
        parts = filter(None, [
            node.get("role", ""),
            node.get("name", ""),
            node.get("value", ""),
            node.get("description", ""),
        ])
        return " ".join(parts).strip()

    @staticmethod
    async def _node_to_locator(page, node: dict):
        """
        Convert an accessibility node back to a Playwright Locator.
        Tries get_by_role(exact=True) → get_by_role(exact=False) → get_by_label.
        Returns None if no live element is found.
        """
        role = (node.get("role") or "").lower()
        name = (node.get("name") or "").strip()
        if not role or not name:
            return None

        for exact in (True, False):
            try:
                loc = page.get_by_role(role, name=name, exact=exact)
                count = await loc.count()
                if count >= 1:
                    return loc.first
            except Exception:
                pass

        # Fallback: form inputs often have no role but do have a label
        try:
            loc = page.get_by_label(name)
            count = await loc.count()
            if count >= 1:
                return loc.first
        except Exception:
            pass

        return None

    async def find(self, page, description: str) -> tuple:
        """
        Deprecated shim — returns (locator, confidence) for the top-1 candidate.
        Prefer find_candidates() for full top-k access.
        """
        candidates = await self.find_candidates(page, description)
        if not candidates:
            return None, 0.0
        loc, desc, score = candidates[0]
        confidence = round(score * 0.9, 3)
        logger.info(
            f"✓ [description-fallback] '{desc[:50]}' "
            f"similarity={score:.0%} → confidence={confidence:.0%}"
        )
        return loc, confidence


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
