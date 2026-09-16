---
description: Element resolution cascade — 3 phases, confidence thresholds, AI fallback chain
globs:
  - "stepper/engine/resolvers/**/*.py"
---

## Element Resolution Cascade

Lives in `stepper/engine/resolvers/`. Orchestrated by `element_resolver.py`.

```
  cfg dict  (role / label / placeholder / text / id / css / xpath)
       │
       ▼
  PHASE 1 — Deterministic  (stepper/engine/resolvers/strategies.py)
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

  PHASE 3 — AI Pick  (stepper/engine/resolvers/ai_pick_resolver.py)
  ────────────────────────────────────────────────────────────────
  Provider chain (cheapest first):  Groq → Gemini → Claude
  confidence ≥ 0.70 → act
  all providers fail → fall back to top semantic result

  Confidence constants:
  CONFIDENCE_AUTO   0.80   auto-act, no warning
  CONFIDENCE_WARN   0.50   warn but still act
```

### When adding a new resolver strategy

1. Implement the `ResolverStrategy` interface from `stepper/engine/interfaces.py`
2. Assign a priority between 10–70 (or beyond 70 for a lower-priority fallback)
3. Register it in `element_resolver.py`'s strategy list
4. Keep deterministic strategies stateless — they must not modify page state

### cfg key → strategy mapping

POMs do not build cfg dicts by hand — `Locator.to_cfg()` produces one, dropping any
field left as `None`. A cfg may therefore carry several keys at once; the resolver
walks its strategies in ascending **strategy** priority and stops at the first unique
match.

```python
# Locator(role="button", name="Submit", css=".submit-btn").to_cfg()
{"role": "button", "name": "Submit", "css": ".submit-btn"}
# → RoleResolver (10) tried first, CssResolver (60) only if that is not unique
```

Ordering comes from the strategy classes' own `priority` attributes, listed in the
table above — **not** from anything inside the cfg. A `"priority"` key in a cfg dict is
read only by the legacy cfg-list helpers in `poms/shared/base_page.py`, which strip it
before calling the resolver. Don't add one to new code.


## The cascade runs for assertions too — and that is a trap

`assert_visible` and `assert_text` resolve their element through this same cascade,
fuzzy fallbacks included. A cfg that matches nothing does not fail: it falls through
to the zero-selector path and `KeywordFuzzyResolver` matches against the step's
`description` instead.

```
Deterministic cascade failed — falling through to zero-selector path
✓ [keyword-fuzzy] single match → confidence 85%
```

That forgiveness is correct for an action that *acts* — you want the click to land
after a redesign. It is wrong for one that *checks*, because it means the assertion
can pass by finding a different element than the one it names, which is the one
behaviour an assertion must not have.

Known and unfixed; see [playwright-pitfalls.md](../../docs/playwright-pitfalls.md)
#7. When you need a check that really fails:

- `assert_count` with an exact expectation, or
- a POM state method that reads the DOM directly — `locator_count()`,
  `is_logged_in()` — since those bypass the resolver entirely.

When adding a new `assert_*` action, decide deliberately whether it should resolve
strictly rather than inheriting the cascade by default.
