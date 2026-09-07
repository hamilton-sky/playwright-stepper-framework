---
name: review
description: Review code changes against stepper framework architectural rules and conventions.
argument-hint: "[file-path | 'staged' | 'last']"
---

Review code at $ARGUMENTS against stepper framework standards.

- `staged` or empty → review `git diff --staged`
- `last` → review `git diff HEAD~1 HEAD`
- file path → review that specific file

## Checklist

### POM layer (`poms/*/pages/*.py`)

- [ ] Every `fill()` / `click()` target is a `Locator` object (not a plain CSS string)
- [ ] Every `Locator` sets `description=` — Phase 2 embeds it for semantic resolution
- [ ] Semantic fields (`role`/`name`, `label`, `placeholder`) filled in where they exist; `css`/`xpath` are fallbacks
- [ ] Interactions go through `_interact(locator, "fill"|"click")`, not direct driver calls
- [ ] No new `_CFG` lists or `"priority"` keys — that convention is superseded by `Locator`
- [ ] POM still works with `resolver=None` and `behaviour=None`
- [ ] No imports from `stepper/` — POMs must not depend on the glue layer
- [ ] No flow logic (no multi-page loops, no orchestration)
- [ ] No hardcoded credentials or environment values
- [ ] Read-only operations (text reads, count checks) may use plain CSS strings — that's fine

### Glue layer (`stepper/sites/*/pages/*.py`)

- [ ] POMs built via `self._build_pom(...)` with `page=`, `resolver=` and `behaviour=`
- [ ] No raw `page.locator("css-string")` calls — selectors belong in POM `Locator`s
- [ ] `action_name` matches the `"action"` key used in workflow JSON, and starts with `f"{site}_"`
- [ ] `_execute` signature is `(self, page, step, resolver, context, behaviour=None)` — five params, default on `behaviour`
- [ ] `execute()` is NOT overridden (it is the template method)
- [ ] Settings loaded from the site's `config.load_settings()`, not hardcoded

### Workflow JSON (`stepper/sites/*/workflows/*.json`)

- [ ] No CSS selectors or XPath strings in step definitions
- [ ] Step `"action"` values match registered action names
- [ ] Variable interpolation uses `${context.var}` syntax

### General

- [ ] Dependency direction respected: Flow → Glue → POM (never reversed)
- [ ] New site BasePage inherits `SharedBasePage` from `poms.shared.base_page`
- [ ] New action strategy class implements `_execute` (not `execute` directly)

## Report format

List each item as PASS / FAIL / N/A. For failures, include the file path, line number, and the specific fix required.
