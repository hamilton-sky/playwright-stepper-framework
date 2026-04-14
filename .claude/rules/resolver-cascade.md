---
description: Element resolution cascade — 3 phases, confidence thresholds, AI fallback chain
globs:
  - "stepper/stepper/resolvers/**/*.py"
---

## Element Resolution Cascade

Lives in `stepper/stepper/resolvers/`. Orchestrated by `element_resolver.py`.

```
  cfg dict  (role / label / placeholder / text / id / css / xpath)
       │
       ▼
  PHASE 1 — Deterministic  (stepper/stepper/resolvers/strategies.py)
  ────────────────────────────────────────────────────────────────
  Priority  Strategy             Playwright call
  ────────  ───────────────────  ─────────────────────────────
  10        RoleResolver         page.get_by_role(role, name=name)
  20        LabelResolver        page.get_by_label(label)
  30        PlaceholderResolver  page.get_by_placeholder(placeholder)
  40        TextResolver         page.get_by_text(text)
  50        IdResolver           page.locator(f"#{id}")
  60        CssResolver          page.locator(css)
  70        XPathResolver        page.locator(f"xpath={xpath}")

  Exactly 1 match → act immediately
  0 or 2+ matches → Phase 2

  PHASE 2 — Semantic Filter
  ────────────────────────────────────────────────────────────────
  Model:   MiniLM-L6-v2 (sentence-transformers)
  Method:  embed cfg description → cosine similarity vs. element text
  score ≥ 0.80 and exactly 1 → act
  2+ shortlisted at threshold → Phase 3

  PHASE 3 — AI Pick  (stepper/stepper/resolvers/ai_pick_resolver.py)
  ────────────────────────────────────────────────────────────────
  Provider chain (cheapest first):  Groq → Gemini → Claude
  confidence ≥ 0.70 → act
  all providers fail → fall back to top semantic result

  Confidence constants:
  CONFIDENCE_AUTO   0.80   auto-act, no warning
  CONFIDENCE_WARN   0.50   warn but still act
```

### When adding a new resolver strategy

1. Implement the `ResolverStrategy` interface from `stepper/stepper/interfaces.py`
2. Assign a priority between 10–70 (or beyond 70 for a lower-priority fallback)
3. Register it in `element_resolver.py`'s strategy list
4. Keep deterministic strategies stateless — they must not modify page state

### cfg key → strategy mapping

A cfg dict can contain multiple keys. The resolver tries each applicable strategy in ascending priority order and stops at the first unique match.

```python
# This cfg will try RoleResolver first, then CssResolver
{"role": "button", "name": "Submit", "css": ".submit-btn", "priority": 10}
```
