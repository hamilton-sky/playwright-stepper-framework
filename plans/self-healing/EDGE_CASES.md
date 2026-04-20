# Self-Healing Planner — Edge Cases

## Category 1: Healer Cannot Produce Valid Replacement

### EC-1.1: Claude returns unknown action name
- **Trigger**: Claude hallucinates `{"action": "click_button"}` not in registry
- **Current behavior**: would reach `ActionRegistry.create()` and raise `ValueError`
- **Expected behavior**: `ClaudeHealer` validates action names before returning;
  raises `HealingError("Unknown action in replacement: click_button")`
- **Handled in**: Phase 2 — post-parse validation in `ClaudeHealer.heal()`

### EC-1.2: Claude returns empty array
- **Trigger**: Claude responds `[]` (no replacement steps)
- **Expected behavior**: `ClaudeHealer` raises `HealingError("Healer returned no steps")`
- **Handled in**: Phase 2

### EC-1.3: Claude API unavailable or rate-limited
- **Trigger**: `anthropic.APIError` raised during healing call
- **Expected behavior**: `ClaudeHealer.heal()` lets the exception propagate as
  `HealingError`; `StepRunner` logs warning, exhausts remaining heal attempts,
  surfaces original error
- **Handled in**: Phase 3 — healing exceptions caught in StepRunner loop

### EC-1.4: Replacement steps also fail
- **Trigger**: Claude suggests a plausible step, but it also fails (wrong element)
- **Expected behavior**: StepRunner increments `heal_attempt`, tries healing again
  up to `max_heal_attempts`; after exhaustion, surfaces the original error
- **Handled in**: Phase 3

---

## Category 2: DOM Snapshot Failures

### EC-2.1: Page mid-navigation when snapshot taken
- **Trigger**: Step failed during navigation; `page.content()` returns partial HTML
- **Expected behavior**: `DOMSnapshot.capture()` returns whatever is available;
  Claude does its best; may result in `HealingError` if context is insufficient
- **Handled in**: Phase 1 — `DOMSnapshot` never raises, returns partial content

### EC-2.2: Page content is extremely large (> 500KB)
- **Trigger**: SPA with embedded data, SVGs, or large inline styles
- **Expected behavior**: stripped + truncated to 8000 chars; `<!-- truncated -->` appended
- **Handled in**: Phase 1

### EC-2.3: `page.content()` itself raises
- **Trigger**: Browser context closed mid-test, or Playwright timeout
- **Expected behavior**: `DOMSnapshot.capture()` catches all exceptions, returns `""`
- **Handled in**: Phase 1

---

## Category 3: Configuration Edge Cases

### EC-3.1: `max_heal_attempts` set to a very large number
- **Trigger**: Workflow JSON `settings.max_heal_attempts: 100`
- **Expected behavior**: StepRunner clamps to `min(max_heal_attempts, 3)`
- **Handled in**: Phase 3

### EC-3.2: Step opts out with `"heal": false`
- **Trigger**: Assertion step or count check has `"heal": false` in workflow JSON
- **Expected behavior**: healing loop skipped entirely for that step; original error surfaces
- **Handled in**: Phases 3–4 — `getattr(step, 'heal', True) is not False` check

### EC-3.3: Healing disabled but `--heal 0` not passed
- **Trigger**: Default behaviour — user didn't pass `--heal`
- **Expected behavior**: `healer=None` passed to StepRunner; healing loop branch
  never entered; zero API calls; zero behaviour change
- **Handled in**: Phase 4

### EC-3.4: `ANTHROPIC_API_KEY` not set but `--heal N` passed
- **Trigger**: CI environment without API key
- **Expected behavior**: `main.py` detects missing key, logs warning, disables healer
  (passes `healer=None`); workflow runs without healing
- **Handled in**: Phase 4

---

---

## Category 4: Shadow DOM and iframes

### EC-4.1: Element lives inside a shadow root (web components)
- **Trigger**: Site uses custom elements (`<my-button>`, `<mat-select>`, etc.) —
  `querySelectorAll` on the document does not pierce shadow roots by default.
  Strategy 1 (embed-first interactive element extraction) returns an empty or
  incomplete list, causing the cascade to fall straight to aria snapshot.
- **Expected behavior**: Cascade degrades gracefully to Strategy 2 (aria snapshot),
  which Playwright's accessibility engine *does* pierce into shadow DOM.
  AiHealer receives aria context and can suggest an XPath or CSS deep combinator.
- **Handled in**: Phase 1 — aria snapshot fallback (score < 0.50 path)
- **Limitation**: The healed cfg will likely be an xpath or deep CSS selector;
  MiniLM embed match won't find it on the next run via Strategy 1 either.
  Cache writeback still works — the cache stores the xpath directly and injects
  it at priority 0 on subsequent runs, bypassing Strategy 1 entirely.

### EC-4.2: Element lives inside an iframe
- **Trigger**: Site embeds a third-party widget (payment form, chat widget) in an
  iframe — both `querySelectorAll` and `page.accessibility.snapshot()` are scoped
  to the top-level frame.
- **Expected behavior**: All DOM strategies return no match for the target element.
  AiHealer receives an empty/minimal context and is likely to raise `HealingError`.
  StepRunner surfaces the original error after exhausting heal attempts.
- **Workaround**: The glue action should use `page.frame()` or `page.frame_locator()`
  directly — iframe interactions are out of scope for generic healing and should be
  implemented explicitly in the POM.
- **Limitation**: Healing cannot cross frame boundaries. Document this in the glue
  layer rules: if a POM method targets an iframe, set `"heal": false` on that step.

---

## Category 5: Healed But Wrong

### EC-5.1: Healer clicks the correct-looking but semantically wrong element
- **Trigger**: A page has two similar buttons ("Add to List" and "Add to Cart").
  The healer finds the wrong one, it clicks without error, step passes.
- **Current behavior**: `status="healed"`, workflow continues — wrong action taken.
- **Mitigation**: This is an accepted limitation of heal-then-verify. Healing is
  a safety net, not a guarantee of correctness. Steps where semantic correctness
  is critical (checkout, delete, confirm) should use `"heal": false`.
- **Recommendation**: See Known Limitations below.

---

## Known Limitations
- Healing works at the **step level** — if a workflow's overall structure is wrong
  (e.g. wrong site, wrong page flow), healing a single step won't fix it.
- `DOMSnapshot` strips `<script>` content — dynamic JS-rendered elements visible in
  the browser may not appear in the snapshot; Claude's suggestions may miss them.
- Self-healing adds latency (embed + optional AI round-trip per healing attempt).
  Use `"heal": false` on time-sensitive or high-stakes steps.
- Recursive `StepRunner.run()` for replacement steps means healing cannot itself
  trigger another healing loop (replacement steps run without a healer).
- Shadow DOM: Strategy 1 embed cannot see inside custom elements; cascade falls
  to aria snapshot. Cache writeback still works via stored xpath/CSS deep selector.
- iframes: healing cannot cross frame boundaries. Use `"heal": false` on iframe steps.
- **Healed but wrong**: healing proves a step ran without error, not that it performed
  the correct semantic action. Use `"heal": false` on destructive or high-stakes steps
  (checkout, delete, confirm, payment).
