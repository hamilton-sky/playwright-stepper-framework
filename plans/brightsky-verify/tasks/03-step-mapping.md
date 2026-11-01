# Map BrightSky steps to strict stepper steps

Type: task
Status: open
Blocked by: 02
Test first: yes
Level: 3
Touches: stepper/brightsky/mapping.py, stepper/tests/unit/test_brightsky_mapping.py

`stepper/brightsky/mapping.py` (new) is pure: no I/O, no Playwright. It turns a validated
`WorkflowDetail` (from ticket 02's `models.py`) into a `MappedWorkflow`, or raises
`UnmappableStep(step_number, reason)`. It is level 3 and on the `Sensitive:` line
because it owns two gates:
- **The host guard.** It stops a stored workflow from steering the headless browser to an
  arbitrary URL.
- **`extra.strict: true` on every acting step.** This keeps a wrong element from being
  clicked, reported `passed` and auto-verified.

Probe both as a hostile caller would.

**`map_version(detail) -> MappedWorkflow`**
- **Step 1 navigates first.** A `navigate` StepConfig goes to
  `https://<host><path>`:
  - host is the step's `expectedDomain` or, when that is absent, the workflow's `site`;
  - path is `expectedUrl` when it starts with `/` and `matchMode` is absent or
    `startsWith`, else `/`.
  - The host guard: the host must equal `detail.site` or end with `"." + detail.site`,
    compared lower-case. It must hold no `@`, `:`, `/`, whitespace or `\`, and the site
    must not be an IP literal. Anything else is `UnmappableStep(1, "navigate host <h> is
    not the workflow's site <s>")`.
  - Every later step's `expectedDomain`, when present, passes the same check.
  - The navigate step's description is `"Step 1: open <url>"`, and it is in
    `step_numbers` as step 1. It has no expectation. So ticket 05 can count a failed
    navigation as step 1 failing.
- **Element cfg from `target`.**
  - Role and accessibleName both non-blank: `{"role": role, "name": accessibleName}`.
  - accessibleName without a role: `{"text": accessibleName}`.
  - A role without an accessibleName never goes into the cfg; it only chooses the action
    below. `RoleResolver` (priority 10, first in the cascade) calls `get_by_role(role)`
    with no name, which matches every element of that role, and a strict lookup takes the
    first match, so a bare role would hit the wrong element.
  - The first selector is added by kind: one starting `//` or `(/` → `"xpath"`; one
    matching `^#[A-Za-z][\w-]*$` → `"id"` (without the `#`); otherwise `"css"`.
  - No target, or a target giving none of these: `UnmappableStep(n, "step has no
    target")`.
- **Action.**
  - Role `textbox|searchbox|spinbutton`, or outcome kind `value_set` → `fill`, with
    `input_value` the first `'…'` or `"…"` quoted text in the title, else in the
    explanation. With none: `UnmappableStep(n, "no value to type: quote it in the
    title")`.
  - A `fill` whose outcome is `url_change` sets `extra.press_enter: true`.
  - Role `combobox|listbox|slider` → `UnmappableStep(n, "role <r> is not supported
    yet")`.
  - Every other role, or selectors only → `click`.
- **Every acting step** has:
  - `extra.strict: true`;
  - `description` `"Step <n>: <title>"`, which is unique and is the key into
    `step_numbers` and `expectations`;
  - `heal_assert {"url_contains": urlContains}` when the outcome is `url_change` with a
    `urlContains`.
- **`StepExpectation`** (frozen dataclass) records:
  - `start_url` and `match_mode`: the step's `expectedUrl` and `matchMode`, only for
    steps after the first;
  - the outcome: kind plus the outcome target's element cfg built by the same rules, or
    `urlContains`.
  - An unknown `matchMode` or outcome kind is `UnmappableStep`.
- **Stored text never reaches the engine's template or env lookups.**
  - Any mapped string (description, input value, element values, URL) containing `{{`
    → `UnmappableStep(n, "contains a {{…}} template reference")`. StepRunner fails a
    step whose reference the context cannot answer, and the planner would substitute
    it.
  - An input value starting with `ENV:` or `${ENV:` → `UnmappableStep(n, "value names
    an environment variable")`. `_resolve_input_value` in `stepper/engine/actions/_common.py` would
    otherwise type the runner's own env (the bridge token, AI keys) into the page.
- **`url_matches(pathname, expected, mode)`** mirrors bright-sky's `matchUrl`:
  `startsWith` is the default, `includes` is substring, and `regex` uses `re.search`,
  falling back to `startsWith` when the pattern does not compile.

## Not in this ticket

- Checking expectations against a live page; ticket 05's `ExpectationHook` uses
  `url_matches` and the expectations built here.
- The reverse direction, a healed element cfg back to a BrightSky target
  (the new `stepper/brightsky/targets.py`, its own ticket).
- Building the proposal body; ticket 06 copies the original steps and swaps targets.

## Done when

- `python3 -m pytest stepper/tests/unit/test_brightsky_mapping.py -q` passes. It covers
  every target kind (role+name, text-only, a css selector, an xpath selector, an `#id`
  selector, and role+name plus a selector), and each `UnmappableStep` reason above.
- In the same file, the pilot's three steps from bright-sky's `pilot-workflows.ts`,
  copied as a fixture, map to a navigate to `https://openlibrary.org/`, a `fill` of
  "The Hobbit" with `press_enter`, then two clicks, and every acting step has
  `extra["strict"] is True`. A target of role `textbox`, no accessibleName and selectors
  `['[placeholder="Search"]']` maps to a `fill` whose element is exactly
  `{"css": '[placeholder="Search"]'}`, with no `role` key.
- In the same file, the host guard rejects `evil.com`, `openlibrary.org.evil.com`,
  `user@openlibrary.org`, `openlibrary.org:8080`, `127.0.0.1` and `openlibrary.org/..`,
  each with an `UnmappableStep` naming step 1, and a title quoting
  `'ENV:BRIGHTSKY_BRIDGE_TOKEN'` or `'{{token}}'` raises `UnmappableStep`.
- In the same file, `url_matches` agrees with bright-sky's `matchUrl` on `startsWith`,
  `includes`, a valid `regex` and an invalid regex.
- All existing tests still pass: `python3 -m pytest stepper/tests/unit/ -q`.

```check
# The conductor runs this block before review.
$ python3 -m pytest stepper/tests/unit/test_brightsky_mapping.py -q
prints passed
$ python3 -m pytest stepper/tests/unit/ -q
prints passed
```

## Reference

- spec.md § Decisions ("Strict acting steps", "Fill values"), § Edge cases
- map.md § Decisions so far (target, outcome and matchUrl facts)
- `stepper/engine/actions/_common.py` `_strict`, `stepper/engine/actions/basic.py`
  `ClickAction`/`FillAction`, `stepper/engine/resolvers/strategies.py` `RoleResolver`
  (`name` key)
- `/home/claude/bright-sky/backend/src/workflow-store/pilot-workflows.ts`,
  `/home/claude/bright-sky/backend/src/workflow-scenarios/url-match.utils.ts` (read only)

## Answer

