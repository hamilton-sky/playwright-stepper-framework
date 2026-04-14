---
description: Three-layer contract — dependency direction, what belongs where, anti-patterns
globs:
  - "poms/**/*.py"
  - "stepper/sites/**/*.py"
  - "stepper/sites/**/*.json"
---

## Three-Layer Contract

```
  Layer   Location                      Responsibility
  ──────  ────────────────────────────  ──────────────────────────────────────────
  POM     poms/*/pages/                 Selectors + raw page interactions only.
                                        No flow logic. No credentials.
                                        All interactive locators are cfg lists.

  Glue    stepper/sites/*/pages/        Wraps POM into a named Stepper behavior.
                                        One action, one job.
                                        Always injects page=page, resolver=resolver.

  Flow    stepper/sites/*/workflows/    Controls order, conditions, variables.
          *.json                        No selectors. No imperative logic.
```

**Dependency direction: Flow → Glue → POM. Never reversed.**

### Belongs in POM
- Locator definitions (cfg lists)
- Low-level page interaction methods (fill, click, wait, read text)
- Page navigation (`open()`, `goto()`)
- State reads (`get_book_count()`, `is_logged_in()`)

### Belongs in Glue
- Mapping a workflow step to one or more POM calls
- Reading step params from `step.params`
- Storing results into `context`
- Short conditional logic specific to one action

### Belongs in Flow (JSON)
- Sequence of steps
- Conditional execution (`when:` clauses)
- Variable interpolation (`${context.var}`)
- Retry / loop constructs (`forEach:`)
- Parallel execution blocks

### Anti-patterns — never do these

| Anti-pattern | Why wrong |
|---|---|
| POM imports from `stepper/sites/` | Reverses dependency direction |
| Glue calls `page.locator()` directly with CSS strings | Bypasses resolver cascade |
| Flow JSON contains CSS selectors | Mixes selector concerns into flow |
| Glue constructs POM without `resolver=resolver` | Disables the entire cascade |
| POM contains `for book in books:` multi-page loop | Flow logic in wrong layer |
| Credentials hardcoded in POM or Glue | Should come from config/env |
