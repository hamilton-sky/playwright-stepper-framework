---
name: verify-layers
description: Audit the entire codebase for three-layer contract violations — dependency direction, cfg list rule, resolver injection.
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

## Check 2 — Glue using raw Playwright locators instead of POM cfg lists (HIGH)

```
grep -rn "page\.locator\s*(" stepper/sites/
grep -rn "page\.get_by_role\s*(" stepper/sites/
grep -rn "page\.get_by_label\s*(" stepper/sites/
```
Any match = **VIOLATION**: Glue is calling Playwright directly, bypassing resolver cascade. Selectors belong in POM cfg lists.

---

## Check 3 — POM construction without resolver injection (HIGH)

In glue files, find POM constructors called without `resolver=`:
```
grep -rn "Page(" stepper/sites/
```
For each match, check whether `resolver=resolver` is present. Missing = **VIOLATION**.

---

## Check 4 — Selectors in workflow JSON (MEDIUM)

```
grep -rn "css\|xpath\|locator\|#[a-z]" stepper/sites/*/workflows/
```
Any CSS/XPath value in a JSON workflow step = **VIOLATION**: selector logic belongs in POM cfg lists.

---

## Check 5 — Plain strings on interactive POM methods (MEDIUM)

```
grep -rn "\.fill\s*(\|\.click\s*(" poms/
```
For each match, check if the locator argument is a cfg list call or a plain string. Plain string = **VIOLATION**.

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
