# Describe a healed element as a BrightSky target

Type: task
Status: open
Blocked by: 02, 03
Test first: yes
Level: 2
Touches: stepper/brightsky/targets.py, stepper/tests/unit/test_brightsky_targets.py

`stepper/brightsky/targets.py` (new) is pure: no I/O, no Playwright, no imports from the
rest of `stepper.brightsky`. A proposal needs each healed step's new element written the
way the store reads a target, and this module does that one conversion.

The conversion must keep the step's action. `map_version` picks `fill` from the
target's role (textbox, searchbox, spinbutton) or a `value_set` outcome, and maps
"selectors only" to `click`. A heal often gives a role-less element (`placeholder`,
`css`, `id`: AiHealer's own prompt example heals a fill to `{"placeholder": "Username"}`),
so without the original role the proposed version would turn a text-entry step, such as
the pilot's step 1, into a click that types nothing. The test file round-trips through
`map_version` to prove it, which is why this ticket is blocked by 03.

**`target_from_element(element: dict, original: dict | None = None) -> dict | None`**
- `original` is the step's stored BrightSky target (`step["target"]`), or None.
- When `element` gives no role+name, the result keeps only `original`'s non-blank `role`
  beside the healed selectors. That role is enough for `map_version` to choose `fill`,
  and `map_version` never puts a role without an accessibleName into the lookup cfg.
- `original`'s `accessibleName` is never kept, and neither are its selectors: they are
  what missed. Why (checked in `stepper/engine/resolvers/element_resolver.py`
  `ElementResolver.resolve` and `strategies.py`): the cascade tries strategies in
  priority order and returns the first that finds anything, `RoleResolver` (priority 10)
  comes before placeholder (30), id (50) and css (60), and a strict lookup takes the
  first of several matches. A stale role+name that matches nothing falls through to the
  healed selector, but one that matches some element (the step healed because its
  outcome was not met, or the page has another field of that name) wins over the
  healed selector, and the proposed version fails, or acts on the wrong element, on
  every run.
- A role+name from `element` always wins over `original`'s role.
- It builds a BrightSky target `{role?, accessibleName?, selectors, score: 0.8,
  grounding: "current_page"}` from a stepper element cfg:
  - `role`+`name` → `role` and `accessibleName`;
  - `css` or `xpath` → `selectors: [value]`;
  - `id` → `selectors: ["#" + id]`;
  - `placeholder` → `selectors: ['[placeholder="…"]']`, with `"` and `\` escaped.
  - Several keys combine: role+name plus a css gives both.
- Return None when the result passes neither of bright-sky's `readPlanStepTarget` rules
  (a non-blank role plus accessibleName, or at least one selector). A text-only or
  label-only element is None, as is a non-dict or an empty dict.
- A selector longer than 1024 characters is dropped. (An element cfg gives at most four
  selectors, so the DTO's limit of 5 always holds.)
- Every value it copies must be a non-blank str; anything else is ignored.

## Not in this ticket

- The forward direction, a BrightSky target to an element cfg, which is part of
  `mapping.map_version` (its own ticket).
- Putting the target into a proposal and choosing its source and note; ticket 06.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_targets.py -q` passes. Its tests
  show the target for role+name, css, xpath, id, placeholder (including one with a `"`
  in it) and role+name plus css.
- In the same file, `{"text": "x"}`, `{"label": "x"}`, `{}`, `{"role": "link", "name": "  "}`
  and a non-dict each return None, and a 2000-character css is dropped.
- In the same file, the round trip keeps the action: a pilot-like step 1 (target role
  `textbox`, accessibleName `Search`, title `Search for 'The Hobbit'`, outcome
  `url_change`), healed to `{"placeholder": "Search"}`, has its target replaced by
  `target_from_element(healed, original=step["target"])`; the step list, read with
  `WorkflowDetail.from_json` and passed to `map_version`, gives step 1 as a `fill` with
  `input_value` `The Hobbit` and `press_enter`, not a `click`, and its element cfg
  contains the healed selector (`css` `[placeholder="Search"]`) and neither `name` nor
  `role` nor the stale `Search` accessibleName. The same holds for a `css` and an `id`
  heal, and a role+name heal to `searchbox` "Find" keeps `searchbox` and `Find` in the
  cfg and drops the original name.
- In the same file, every non-None result passes a copy of `readPlanStepTarget`'s two
  rules written as a test helper (role and accessibleName non-blank, or at least one
  selector; `score` within 0..1; `grounding` `current_page`).
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_targets.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Interfaces (`targets.target_from_element`, `mapping.map_version`),
  § Edge cases
- map.md § Decisions so far (the target facts)
- `/home/claude/bright-sky/backend/src/agents/infrastructure/services/element-search/step-target.ts`
  `readPlanStepTarget` (read only)

## Answer
