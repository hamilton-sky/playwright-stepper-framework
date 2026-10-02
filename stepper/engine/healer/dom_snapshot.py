"""
healer/dom_snapshot.py — Embed-first DOM capture utility for AiHealer.

Walks an embedding-driven decision tree to keep the AI prompt as small as
possible. The cheapest outcome (Strategy 1, unique high-confidence match)
needs zero AI tokens — we synthesise a healed cfg from the element's own
attributes. The most expensive (full ARIA snapshot) is only reached when no
candidate scores above 0.50.

  ≥ 0.85, unique     → embed_direct      (no AI call, healed_cfg ready)
  ≥ 0.85, ambiguous  → embed_candidates  (~20-40 tokens)
  clear winner       → embed_direct      (no AI call — see below)
  0.50-0.85          → scoped DOM area   (~40-150 tokens)
  < 0.50             → aria snapshot     (~200-500 tokens)

Clear winner:
  The 0.85 bar alone never fired on a real login form. Measured on the SauceDemo
  fixture, MiniLM ranks the right element first for all three heal steps — by
  0.31 to 0.45 over the runner-up — at 0.73-0.79, so every heal fell to the
  scoped band and needed an AI pick. An absolute score says how alike two
  strings are; how far the best candidate leads the rest is what says the
  choice is unambiguous. So a candidate is also healed directly when all hold:

    - it is the best candidate on the page, and it suits the action: a fill
      needs a field that takes text, a click a clickable, visible, enabled,
      uncovered element (actions not modelled here never qualify)
    - its MiniLM score is ≥ _LOW_THRESHOLD
    - it leads the next candidate of any kind by ≥ _MARGIN — or, when it is
      the only candidate, scores ≥ _LONE_MIN
    - the cross-encoder, when loaded, also ranks it first

Cross-encoder re-ranking:
  After MiniLM shortlists the top _TOP_N candidates, a cross-encoder
  (cross-encoder/ms-marco-MiniLM-L-6-v2) re-scores each (query, element)
  pair jointly — seeing both strings at once — producing a more accurate
  final ranking. Falls back to MiniLM order when the model is not installed.
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any

from stepper.engine.interfaces import StepConfig
from stepper.engine.healer.interfaces import DomPayload
from stepper.engine.resolvers.strategies import SemanticResolver

logger = logging.getLogger(__name__)

_HIGH_THRESHOLD = 0.85
_LOW_THRESHOLD = 0.50
_TOP_N = 5
_MARGIN = 0.25
# With no other candidate there is no runner-up to lead, and the margin
# degenerates to the score itself. That is exactly the case where the
# intended element is gone and something unrelated is left, so a lone candidate
# must clear a higher bar than the floor a contested one does.
_LONE_MIN = 0.65

# What each action can act on. The tag comes from el.tagName, `type` from the
# attribute; `role` is the explicit role attribute or, failing that, the
# lower-cased tag (see _ELEMENT_QUERY_JS), so tag-named roles are harmless here.
_TEXT_INPUT_TYPES_EXCLUDED = {
    "submit", "button", "reset", "image", "checkbox", "radio", "hidden", "file",
    "range", "color",
}
_CLICKABLE_INPUT_TYPES = {"submit", "button", "reset", "image", "checkbox", "radio"}
_INPUT_ROLES = {
    "text": "textbox", "email": "textbox", "tel": "textbox", "url": "textbox",
    "search": "searchbox", "number": "spinbutton", "range": "slider",
    "checkbox": "checkbox", "radio": "radio",
    "submit": "button", "button": "button", "reset": "button", "image": "button",
}
_CLICKABLE_ROLES = {
    "button", "link", "menuitem", "tab", "checkbox", "radio", "switch", "option",
}

_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CROSS_ENCODER_LOCAL = (
    pathlib.Path(__file__).parents[2] / "models" / "cross-encoder-ms-marco-MiniLM-L-6-v2"
)

_ELEMENT_QUERY_JS = """() => {
  // A CSS selector that matches this element and nothing else on the page,
  // computed by the browser at capture time. Every healed cfg carries it, so a
  // heal never depends on the role/name synthesis alone: get_by_role is tried
  // first, and if the synthesised role is ever wrong it matches nothing and the
  // resolver falls through to this — rather than to a description guess.
  // Unique AND the target: an intermediate path such as `body > input` can be
  // unique on the page and still be some other element.
  const pins = (s, el) => {
    try { const m = document.querySelectorAll(s); return m.length === 1 && m[0] === el; }
    catch (e) { return false; }
  };
  const selectorFor = el => {
    if (el.id && pins('#' + CSS.escape(el.id), el)) return '#' + CSS.escape(el.id);
    const tag = el.tagName.toLowerCase();
    const nm = el.getAttribute('name');
    if (nm) {
      const s = tag + '[name="' + CSS.escape(nm) + '"]';
      if (pins(s, el)) return s;
    }
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.body; n = n.parentElement) {
      let i = 1;
      for (let sib = n.previousElementSibling; sib; sib = sib.previousElementSibling)
        if (sib.tagName === n.tagName) i++;
      parts.unshift(n.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      const s = 'body > ' + parts.join(' > ');
      if (pins(s, el)) return s;
    }
    return '';
  };
  return [...document.querySelectorAll('button,a,input,select,textarea,[role],[aria-label]')].map(el => ({
    selector:    selectorFor(el),
    // A text-like input with a list attribute (a datalist) is a combobox.
    list:        el.tagName === 'INPUT' && el.hasAttribute('list'),
    tag:         el.tagName,
    text:        el.textContent?.trim().slice(0,80),
    role:        el.getAttribute('role') || el.tagName?.toLowerCase(),
    aria:        el.getAttribute('aria-label'),
    id:          el.id,
    placeholder: el.getAttribute('placeholder'),
    name:        el.getAttribute('name'),
    type:        el.getAttribute('type'),
    title:       el.getAttribute('title'),
    // An <a> is a link only with an href; without one it has no implicit role.
    href:        el.hasAttribute('href'),
    // What fill() and select_option() actually need — an ARIA role is a claim
    // about semantics, not about whether the element takes input.
    editable:    el.isContentEditable === true,
    readonly:    el.readOnly === true,
    // Whether a click or fill could land at all. The clear-winner rule must
    // not heal straight to an element Playwright's actionability checks will
    // refuse — a closed menu's links are in the DOM but not on screen.
    // checkVisibility() is the browser's own answer — display:none on any
    // ancestor, visibility:hidden, content-visibility — where a layout-box test
    // misses visibility:hidden. The box test is the fallback for old engines.
    hidden:      el.checkVisibility
                   ? !el.checkVisibility({visibilityProperty: true})
                   : !(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
    // :disabled includes a control disabled by an ancestor <fieldset>, and
    // aria-disabled applies to descendants, so the ancestor chain is checked.
    disabled:    el.matches(':disabled') || el.closest('[aria-disabled="true"]') !== null,
    // A <select> with multiple or size > 1 is a listbox, not a combobox.
    multirow:    el.tagName === 'SELECT' && (el.multiple || el.size > 1),
    // Whether something else sits on top of the element's centre — a fixed
    // overlay, a cookie banner. Playwright's click waits for the target to
    // receive events and would time out. Off-screen is not covered: Playwright
    // scrolls into view first.
    covered:     (() => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return false;
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
      const hit = document.elementFromPoint(x, y);
      return !!hit && hit !== el && !el.contains(hit) && !hit.contains(el);
    })(),
    // A button-shaped <input> carries its whole visible label in `value`, and
    // an <input> has no textContent, so without this the healer sees
    // "input login-button submit" for a button that plainly reads "Login".
    //
    // Restricted to submit/button/reset on purpose: `value` on a text or
    // password input is whatever the user typed, and this description is
    // embedded and can be sent to an AI provider. Labels yes, secrets no.
    value:       el.tagName === 'OPTION'
                   ? el.textContent?.trim()
                   : (el.tagName === 'INPUT' &&
                      ['submit', 'button', 'reset'].includes((el.type || '').toLowerCase())
                        ? el.value
                        : undefined)
  }));
}"""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


class _CrossEncoderReranker:
    """
    Lazy singleton wrapping sentence_transformers CrossEncoder.

    rerank() takes the top-N (element, minilm_score) pairs already sorted
    by MiniLM and returns them re-sorted by cross-encoder score.

    The cross-encoder reads (query, element_description) as a single
    concatenated input, so attention flows across both — it understands
    that "fill" + "input" + "text" reinforce each other in a way that
    two independent embedding vectors cannot capture.

    Logits are sigmoid-normalised to [0,1] so the existing threshold
    constants (_HIGH_THRESHOLD, _LOW_THRESHOLD) stay meaningful.

    Degrades gracefully: if model unavailable, rerank() returns input unchanged.
    """

    _instance: "_CrossEncoderReranker | None" = None

    def __init__(self):
        self._model = None
        self._available = False
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
            model_path = str(_CROSS_ENCODER_LOCAL) if _CROSS_ENCODER_LOCAL.exists() else _CROSS_ENCODER_MODEL
            self._model = CrossEncoder(model_path)
            self._available = True
            logger.info("[CrossEncoderReranker] loaded from %s", model_path)
        except ImportError:
            logger.debug("[CrossEncoderReranker] sentence-transformers not installed — skipping re-ranking")
        except Exception as exc:
            logger.warning("[CrossEncoderReranker] could not load model (%s) — skipping re-ranking", exc)

    @classmethod
    def instance(cls) -> "_CrossEncoderReranker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def rerank(
        self, query: str, scored: list[tuple[dict, float]]
    ) -> list[tuple[dict, float]]:
        """
        Re-ranks top-N candidates using the cross-encoder.
        Returns a new list sorted by cross-encoder score descending.
        Falls back to original MiniLM order if the model is unavailable.
        """
        if not self._available or not scored:
            return scored
        try:
            descriptions = [DOMSnapshotCascade._describe_element(el) for el, _ in scored]
            pairs = [[query, desc] for desc in descriptions]
            raw_scores: list[float] = self._model.predict(pairs).tolist()

            # sigmoid normalisation: logit → [0, 1]
            normalised = [1.0 / (1.0 + math.exp(-s)) for s in raw_scores]

            reranked = sorted(
                zip([el for el, _ in scored], normalised),
                key=lambda x: x[1],
                reverse=True,
            )
            logger.debug(
                "[CrossEncoderReranker] re-ranked %d candidates; winner: '%s' (%.3f)",
                len(reranked),
                DOMSnapshotCascade._describe_element(reranked[0][0])[:60],
                reranked[0][1],
            )
            return list(reranked)
        except Exception as exc:
            logger.warning("[CrossEncoderReranker] predict failed (%s) — using MiniLM order", exc)
            return scored


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

        # Phase 1 — MiniLM bi-encoder: score all elements cheaply
        scored = cls._score_elements(query, elements)
        scored.sort(key=lambda x: x[1], reverse=True)
        minilm_ranked = list(scored)

        # Phase 2 — Cross-encoder: re-rank the top _TOP_N candidates with
        # higher accuracy (reads query + element together in one pass)
        top_n = scored[:_TOP_N]
        reranked = _CrossEncoderReranker.instance().rerank(query, top_n)

        # Merge: reranked top-N at the front, remaining lower-ranked after
        rest = scored[_TOP_N:]
        scored = reranked + rest

        top_score = scored[0][1] if scored else 0.0

        if top_score >= _HIGH_THRESHOLD:
            high = [s for s in scored if s[1] >= _HIGH_THRESHOLD]
            if len(high) == 1:
                element = high[0][0]
                return DomPayload(
                    strategy_used="embed_direct",
                    content="",
                    healed_cfg=await cls._pinned_cfg(page, cls._element_to_cfg(element)),
                    token_estimate=0,
                )
            return cls._candidates_payload(high, "embed_candidates")

        winner = cls._clear_winner(step.action, query, minilm_ranked)
        if winner is not None:
            return DomPayload(
                strategy_used="embed_direct",
                content="",
                healed_cfg=await cls._pinned_cfg(page, cls._element_to_cfg(winner)),
                token_estimate=0,
            )

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

    # ── A direct heal must point at the element that was chosen ──────────────

    @staticmethod
    async def _pinned_cfg(page, cfg: dict) -> dict:
        """
        Keep the semantic identifier only if it resolves to the chosen element.

        The resolver tries role/label/placeholder/text before css and stops at
        the first unique match. A role+name built from raw textContent can
        uniquely match a *different* element — a button named by
        aria-labelledby whose icon text is another button's name — and the
        browser-computed selector that pins the real target is never reached.
        So check it on the live page, the way the resolver will call it, and
        if it is ambiguous, missing or another element, heal to the pinned
        selector alone.
        """
        css = cfg.get("css")
        semantic = [k for k in ("role", "label", "placeholder", "text") if k in cfg]
        if not css or not semantic:
            return cfg
        try:
            if "role" in cfg:
                loc = (page.get_by_role(cfg["role"], name=cfg["name"], exact=True)
                       if cfg.get("name") else page.get_by_role(cfg["role"]))
            elif "label" in cfg:
                loc = page.get_by_label(cfg["label"])
            elif "placeholder" in cfg:
                loc = page.get_by_placeholder(cfg["placeholder"])
            else:
                loc = page.get_by_text(cfg["text"], exact=True)
            if await loc.count() == 1 and await loc.evaluate(
                "(e, s) => e === document.querySelector(s)", css
            ):
                return cfg
        except Exception as exc:
            logger.debug(f"[DOMSnapshotCascade] semantic check failed ({exc}) — pinning css")
        logger.info(
            "[DOMSnapshotCascade] semantic identifier does not pin the chosen "
            "element — healing to %s", css,
        )
        return {"priority": cfg.get("priority", 0), "css": css}

    # ── Clear-winner rule ─────────────────────────────────────────────────────

    @staticmethod
    def _fits_action(action: str, el: dict) -> bool | None:
        """
        Whether `el` is something `action` can act on. None for an action this
        does not model — the clear-winner rule then never applies to it.
        """
        tag  = (el.get("tag") or "").upper()
        typ  = (el.get("type") or "").lower()
        role = (el.get("role") or "").lower()
        if action in ("fill", "click", "hover", "select") and (
            el.get("hidden") or el.get("disabled")
        ):
            return False
        if action == "fill":
            # locator.fill() needs a native text input or textarea, or a
            # contenteditable — a <button role="combobox"> has the role and
            # refuses the fill, and the healer would pick it again every attempt.
            if el.get("readonly"):
                return False
            if tag == "INPUT":
                return typ not in _TEXT_INPUT_TYPES_EXCLUDED
            return tag == "TEXTAREA" or bool(el.get("editable"))
        if action in ("click", "hover"):
            if el.get("covered"):
                return False
            if tag == "INPUT":
                return typ in _CLICKABLE_INPUT_TYPES
            return tag in ("BUTTON", "A") or role in _CLICKABLE_ROLES
        if action == "select":
            # select_option() works on a native <select> only.
            return tag == "SELECT"
        return None

    @classmethod
    def _clear_winner(
        cls,
        action: str,
        query: str,
        minilm_ranked: list[tuple[dict, float]],
    ) -> dict | None:
        """
        The element to heal to without an AI call, or None.

        The winner is the best candidate on the whole page, never merely the
        best *suitable* one. Ranking only the suitable candidates let a
        higher-scoring unsuitable element — the real target, when it is a
        disabled tooltip trigger for a hover, a text input for a click — drop
        out, and the runner-up became the "clear winner": the wrong element. So
        every candidate competes; if the top one does not suit the action, or
        does not clearly lead the next candidate of any kind, the AI decides.

        Margins are taken on the MiniLM scores, which are comparable across
        every candidate; the cross-encoder only re-scores the top few, on its
        own scale. It gets a veto instead: if it ranks a different element
        first, the choice is not clear.
        """
        if not minilm_ranked:
            return None
        best, best_score = minilm_ranked[0]
        if not cls._fits_action(action, best):
            return None
        if len(minilm_ranked) == 1:
            runner_up = 0.0
            if best_score < _LONE_MIN:
                return None
        else:
            runner_up = minilm_ranked[1][1]
            # 1e-9: the margin is inclusive, and 0.70 - 0.45 is 0.2499999… in floats.
            if best_score < _LOW_THRESHOLD or best_score - runner_up < _MARGIN - 1e-9:
                return None
        reranked = _CrossEncoderReranker.instance().rerank(query, minilm_ranked[:_TOP_N])
        if not reranked or reranked[0][0] is not best:
            return None
        logger.info(
            "[DOMSnapshotCascade] clear winner for %s: '%s' (%.3f, lead %.3f) — embed_direct",
            action, cls._describe_element(best)[:60], best_score, best_score - runner_up,
        )
        return best

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
        # Include every human-readable attribute so MiniLM sees the full
        # semantic surface: aria-label beats visible text for icon buttons,
        # placeholder beats name for login inputs, title adds tooltip context.
        parts = [
            el.get("role") or "",
            el.get("aria") or "",
            el.get("placeholder") or "",
            (el.get("text") or "").strip(),
            # The label of a button-shaped <input>, and of an <option>. Captured
            # above only where it is a label rather than user input.
            (el.get("value") or "").strip(),
            el.get("title") or "",
            el.get("name") or "",
            el.get("type") or "",
        ]
        return " ".join(p for p in parts if p).strip()

    # ── Cfg synthesis ─────────────────────────────────────────────────────────

    @staticmethod
    def _aria_role(el: dict) -> str:
        """
        A role get_by_role() can resolve. _ELEMENT_QUERY_JS falls back to the
        lower-cased tag when there is no role attribute, and "a", "select" or
        "input" are not ARIA roles — a healed {"role": "select"} resolves to
        nothing. Map those to the element's implicit role; drop the rest.
        """
        role = (el.get("role") or "").strip()
        tag = (el.get("tag") or "").lower()
        if not role or role.lower() != tag:
            return role                      # explicit role attribute, or none
        if tag == "input":
            # The implicit role per type, from HTML-AAM. A type with none — a
            # password, a date — gets none, so the cfg falls to its placeholder
            # or id rather than a role get_by_role() would not find.
            typ = (el.get("type") or "text").lower()
            if el.get("list") and typ in ("text", "search", "email", "tel", "url"):
                return "combobox"            # backed by a <datalist>
            return _INPUT_ROLES.get(typ, "")
        if tag == "a":
            return "link" if el.get("href") else ""
        if tag == "select":
            return "listbox" if el.get("multirow") else "combobox"
        return {"button": "button", "textarea": "textbox"}.get(tag, "")

    @classmethod
    def _element_to_cfg(cls, el: dict) -> dict:
        cfg: dict[str, Any] = {"priority": 0}
        role = cls._aria_role(el)
        text = (el.get("text") or "").strip()
        if (el.get("tag") or "").upper() == "SELECT":
            text = ""   # a select's textContent is every option, not its name
        if not text and role == "button":
            # A button-shaped <input> has no textContent; its value is its
            # accessible name. _ELEMENT_QUERY_JS only collects value for
            # submit/button/reset inputs, so this is never user-typed text.
            text = (el.get("value") or "").strip()
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
        elif not el.get("selector") and tag:
            cfg["css"] = tag
        # The browser-computed unique selector rides along with whatever
        # semantic identifier was chosen. The resolver tries the semantic one
        # first (role 10 … css 60), so it changes nothing when that resolves,
        # and it is the deterministic fallback when it does not.
        if el.get("selector"):
            cfg["css"] = el["selector"]
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
        logger.info(f"[DOMSnapshotCascade] aria fallback ({reason})")
        return DomPayload(
            strategy_used="aria",
            content=content,
            healed_cfg=None,
            token_estimate=_estimate_tokens(content),
        )
