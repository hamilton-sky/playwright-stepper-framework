# Describe a healed element as a BrightSky target

Type: task
Status: resolved
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

- **Built**: `stepper/brightsky/targets.py` (new: `target_from_element`) and
  `stepper/tests/unit/test_brightsky_targets.py` (new). Work started at 14b76b9.
  Test-only commit f961314 first; it failed at collection with
  `ModuleNotFoundError: No module named 'stepper.brightsky.targets'`.
- **Proof**:
  - `python3 -m pytest stepper/tests/unit/test_brightsky_targets.py -q` → `42 passed`.
    `test_each_element_kind_becomes_a_target` asserts the exact target for role+name,
    css, xpath, id (`#searchbox`), placeholder, placeholder with `"`
    (`[placeholder="Say \"hi\""]`), placeholder with `\`, and role+name plus css.
  - Same file: `{"text": "x"}`, `{"label": "x"}`, `{}`, `{"role": "link", "name": "  "}`,
    role-only, name-only, and non-dicts (None, str, list, int) each return None; a
    2000-character css alone gives None and beside an id is dropped (selectors `["#q"]`).
    Non-str / blank values are ignored.
  - Same file, round trip through `WorkflowDetail.from_json` + `map_version`: the
    pilot-like step 1 healed to `{"placeholder": "Search"}`, `{"css": ...}` and
    `{"id": "searchbox"}` each map to `fill`, `input_value == "The Hobbit"`,
    `press_enter` true, element exactly `{"css": '[placeholder="Search"]'}` /
    `{"css": "input.search-bar"}` / `{"id": "searchbox"}` (no `role`, `name`, `text`, no
    `Search` value). A role+name heal to `searchbox` "Find" gives element
    `{"role": "searchbox", "name": "Find"}`. A control test shows that without
    `original` the same heal maps to `click`.
  - Every non-None result passes `_valid_plan_step_target` (readPlanStepTarget's rules:
    role+accessibleName non-blank or a selector, ≤5 selectors each non-blank ≤1024,
    score 0..1, grounding `current_page`, role ≤64, name ≤512).
  - `python3 -m pytest stepper/tests/unit/ -q` → `1990 passed`.
  - Also: Build exit 0, Lint exit 0, acceptance `test_accept_mapping.py` → `37 passed`
    (its 7 targets tests no longer fail).
- **Decisions**:
  - Selectors are listed in the resolver cascade's priority order (placeholder 30,
    id 50, css 60, xpath 70), because `map_version` takes only the first selector.
  - A role longer than 64 or a name longer than 512 characters is ignored like a
    non-str value (readPlanStepTarget refuses the whole target for those), so the role
    falls back to `original`'s role or is left out.
  - Values are copied as given (not stripped); blankness is checked with `strip()`.
    `map_version` strips them when it reads them back.
  - An element's lone `role` (no name) is not used; only `original`'s role is, as the
    ticket says.
- **Shortcuts taken**: none.
- **For later tickets**: ticket 06 should pass `original=step.get("target")` and treat
  None as "nothing to propose". The returned dict is new each call; `original` is not
  changed.
