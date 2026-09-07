---
name: verify-layers
description: Audit the entire codebase for three-layer contract violations — dependency direction, Locator rule, resolver injection.
argument-hint: "[pom|glue|flows|all]"
---

Audit the codebase for three-layer contract violations.

## Target: $ARGUMENTS (default: all)

Run the following checks using Grep across the relevant directories.

---

## Check 1 — POM importing from glue layer (CRITICAL)

Files that should never appear in POM imports:
```
grep -r "from stepper.sites" poms/
grep -r "import stepper.sites" poms/
```
Any match = **VIOLATION**: POM depends on glue layer (reversed dependency).

---

## Check 2 — Glue using raw Playwright locators instead of POM Locators (HIGH)

```
grep -rn "page\.locator\s*(" stepper/sites/
grep -rn "page\.get_by_role\s*(" stepper/sites/
grep -rn "page\.get_by_label\s*(" stepper/sites/
```
Any match = **VIOLATION**: Glue is calling Playwright directly, bypassing the resolver cascade. Selectors belong in POM `Locator`s.

---

## Check 3 — POM construction without resolver injection (HIGH)

In glue files, POMs must be built via `_build_pom`, which makes `page=`, `resolver=`
and `behaviour=` keyword-mandatory:
```
grep -rn "Page(" stepper/sites/
grep -rn "_build_pom(" -A 4 stepper/sites/
```
A direct `SomePage(...)` constructor call, or a `_build_pom` call missing any of the
three keywords = **VIOLATION**.

---

## Check 4 — Selectors in workflow JSON (MEDIUM)

```
grep -rn "css\|xpath\|locator\|#[a-z]" stepper/sites/*/workflows/
```
Any CSS/XPath value in a JSON workflow step = **VIOLATION**: selector logic belongs in POM `Locator`s.
(Exception: `sd_heal_test.json` / `sd_full_heal_flow.json` carry deliberately broken
selectors as healer fixtures.)

---

## Check 5 — Plain strings on interactive POM methods (MEDIUM)

```
grep -rn "\.fill\s*(\|\.click\s*(" poms/
```
For each match, check the locator argument is a `Locator` object routed through
`_interact`, not a plain CSS string. Plain string on an interactive element = **VIOLATION**.

---

## Check 6 — Glue overriding the template method (HIGH)

```
grep -rn "async def execute" stepper/sites/ stepper/engine/pages/
```
Any match = **VIOLATION**: `execute()` is the `ActionStrategy` template method. Overriding
it skips `pre_execute` / `post_execute` and context defaulting. Implement `_execute` instead.
`stepper/tests/unit/test_action_template_method.py` guards this.

---

## Report format

For each check:
- **PASS** if no violations found
- **FAIL** with file path, line number, and description of the violation

Summary at the end:
```
Violations found: N
  - CRITICAL: X
  - HIGH: Y
  - MEDIUM: Z
```

If zero violations: "All layer boundary checks passed."
