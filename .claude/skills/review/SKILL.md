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

- [ ] Every `fill()` / `click()` call uses a cfg list locator (not a plain CSS string)
- [ ] cfg dicts have explicit `"priority"` values; lower = tried first
- [ ] `_resolve_and_fill_any` / `_resolve_and_click_any` used (not direct driver calls for interactive elements)
- [ ] No imports from `stepper/sites/` — POMs must not depend on glue layer
- [ ] No flow logic (no multi-page loops, no orchestration)
- [ ] No hardcoded credentials or environment values
- [ ] Read-only operations (text reads, count checks) may use plain CSS strings — that's fine

### Glue layer (`stepper/sites/*/pages/*.py`)

- [ ] Every POM construction passes `page=page, resolver=resolver`
- [ ] No raw `page.locator("css-string")` calls — selectors belong in POM cfg lists
- [ ] Action name in `register()` matches the `"action"` key used in workflow JSON
- [ ] `_execute` signature is `(self, page, step, resolver, context)`
- [ ] Settings loaded from `config.get_settings()`, not hardcoded

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
