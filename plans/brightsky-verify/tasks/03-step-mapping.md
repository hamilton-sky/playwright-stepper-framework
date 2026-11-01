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

- **Built**: `stepper/brightsky/mapping.py` (new: `map_version`, `MappedWorkflow`,
  `StepExpectation`, `UnmappableStep`, `url_matches`) and
  `stepper/tests/unit/test_brightsky_mapping.py` (new). Test-only commit 3a589c1 first;
  it failed at collection with `ModuleNotFoundError: No module named
  'stepper.brightsky.mapping'`. Work started at 82d5593.
- **Proof**:
  - `python3 -m pytest stepper/tests/unit/test_brightsky_mapping.py -q` → `100 passed`.
    Target kinds: role+name, text-only, css, xpath (`//` and `(/`), `#id` (to `id`
    without `#`), `#a b` (stays css), role+name plus a selector (role, name and the
    first selector), role without a name (selector only), blank name. Every
    `UnmappableStep` reason: no target (missing, blank selectors, role only),
    combobox/listbox/slider, no quoted value, unknown matchMode (step 1 and later),
    unknown outcome kind, element outcome without target, `ENV:` / `${ENV:` / ` ENV:`
    values, `{{` in a value, title, accessibleName, selector, URL path, urlContains
    and outcome target, plus wrong field types. `str(error) == "step N: <reason>"`.
  - Pilot fixture (copied from `pilot-workflows.ts`): `navigate, fill, click, click`;
    navigate url `https://openlibrary.org/`, description
    `Step 1: open https://openlibrary.org/`, step 1, no expectation; fill
    `input_value == "The Hobbit"`, `press_enter` true, heal_assert
    `{"url_contains": "/search"}`; every acting step `extra["strict"] is True`.
    Role `textbox`, no name, selectors `['[placeholder="Search"]']` → `fill` with element
    exactly `{"css": '[placeholder="Search"]'}`.
  - Host guard: `evil.com`, `openlibrary.org.evil.com`, `user@openlibrary.org`,
    `openlibrary.org:8080`, `127.0.0.1`, `openlibrary.org/..` (and `evilopenlibrary.org`,
    backslash, space, `#`, `?`, leading dot, empty) each raise step 1 with
    `navigate host <h> is not the workflow's site openlibrary.org`. Sites `127.0.0.1`,
    `10.0.0.5`, `[::1]`, `::1`, `2130706433`, `0x7f000001`, `evil.com/x`,
    `user@evil.com`, `com` are refused. A later step's bad `expectedDomain` names that
    step. Titles quoting `'ENV:BRIGHTSKY_BRIDGE_TOKEN'` and `'{{token}}'` raise.
  - `url_matches`: startsWith (explicit and None), includes, valid regex (anchored and
    `re.search` substring), invalid regex `([` falling back to startsWith: 12 cases pass.
  - `python3 -m pytest stepper/tests/unit/ -q` → `1860 passed`.
  - Also: Build exit 0, Lint exit 0. Acceptance `test_accept_mapping.py`: 30 passed,
    7 failed, all 7 `ModuleNotFoundError: No module named 'stepper.brightsky.targets'`
    (ticket 11).
- **Decisions**:
  - Hosts must be lower-case DNS labels joined by dots (an allowlist), which refuses
    `@ : / \`, whitespace, `#`, `?` and brackets in one rule. The site must also contain
    a dot and its last label must not be numeric or `0x…` (what browsers parse as an
    IPv4 number), which covers IP literals including `2130706433`. A single-label site
    (`com`, `localhost`) is refused, since it would make every host under it pass.
  - Hostile text in a reason (host, site, role, mode, kind) is shown through
    `unicode_escape` and cut at 100 characters, so a reason printed by the CLI cannot
    carry control characters.
  - A later step's bad domain reads `expected domain <h> is not the workflow's site <s>`
    (the ticket fixes the wording only for step 1).
  - A single quote opens only when no word character precedes it and closes only when
    none follows, so apostrophes ("the author's name, 'J.R.R. Tolkien'") are not quotes,
    and `'Don't Panic'` is one value.
  - The `ENV:` check uses `lstrip()`, so a leading space cannot slip past it.
  - Unsupported roles are checked before the fill choice, so a combobox with a
    `value_set` outcome is still unmappable.
  - `StepExpectation` fields: `start_url`, `match_mode` (None means startsWith, and
    `url_matches` accepts None), `outcome_kind`, `outcome_element`, `url_contains`.
  - An acting step whose description equals the navigate's (title `open <url>` on
    step 1) is unmappable, so `expectations` never keys the navigate.
  - Wrong field types (target, outcome, domain, URL, matchMode, explanation, role, name,
    selectors) are `UnmappableStep`, not a crash.
- **Shortcuts taken**: `url_matches` uses Python `re`, not JS `RegExp`, so a pattern
  that uses syntax only one engine has can match differently; worth a translation layer
  only if a stored regex shows that. Fill values are not length-capped (titles are
  ≤ 200 by the backend DTO).
- **For later tickets**: ticket 05 reads `mapped.expectations[step.description]`; the
  navigate has none. `start_url`/`match_mode` are None for step 1. Ticket 11's
  `target_from_element` output maps back through `_element`: a role with no
  accessibleName only chooses the action, and the first non-blank selector is taken
  by kind (`//`/`(/` xpath, `#ident` id, else css), so a `placeholder` heal must become
  a css selector such as `[placeholder="Search"]`.


## Review findings (round 1, pair review)

Scope of review: ticket file plans/brightsky-verify/tasks/03-step-mapping.md read at 82d5593 (Answer empty there). END = 046a1c4 = HEAD, so no later commits were left out. I did not read the Answer. The Status hunk is open -> resolved. I reviewed /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py and /home/claude/hamilton-sky/playwright-stepper-framework/stepper/tests/unit/test_brightsky_mapping.py, plus the one-line additions to learnings.md and map.md.

Done when, re-run by me: test_brightsky_mapping.py 100 passed; stepper/tests/unit/ 1860 passed. git status is clean afterwards.

Inputs I probed as a hostile caller (level 3):
- site, and expectedDomain on step 1 and on later steps: tried userinfo, port, path, IP, a numeric last label, a single label and upper case. All handled.
- expectedUrl as the navigate path: `//evil.com/a` and `/\evil.com` both stay on the site's host, because the host is fixed before the path.
- target role/accessibleName/selectors, both as wrong types and as blank strings.
- expectedOutcome.kind and matchMode as wrong types.
- Quoted fill values with ENV:, ${ENV: and leading whitespace. The engine's `_resolve_input_value` does not strip; mapping strips, so it is stricter, which is fine.
- `{{` in every field the StepRunner templates (`url`, `input_value`, `element`, `extra`, `description`). All covered.

QUALITY
1. major /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: `_map_step` does `mode not in MATCH_MODES` and `_outcome` does `kind not in OUTCOME_KINDS` on raw stored values without a type check. A stored `"matchMode": []` or `"expectedOutcome": {"kind": []}` / `{"kind": {}}` raises `TypeError: unhashable type` instead of `UnmappableStep`. I confirmed all three by calling `map_version`. The ticket says an unknown matchMode or outcome kind is `UnmappableStep`, and later tickets treat `UnmappableStep` as "post a failed report without running", which is a different path from "an entry that raises". So a hostile or malformed workflow can move itself off the intended path. Fix: read both through `_optional_str` (or check `isinstance(..., str)`) before the membership test, and add list/dict cases to `test_wrong_types_are_unmappable`. Today it only tries the hashable `matchMode: 1`.
2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: the host guard is relative to `detail.site` only, so a site like `nip.io` allows `127.0.0.1.nip.io`, and `co.uk` passes as a site (no public-suffix check). This follows the ticket as written, but the site is stored data too. Worth a note for the spec or a later allowlist.
3. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: an empty-string `expectedDomain` on step 1 is treated as present and rejected, not as absent with a fallback to site. Use `or detail.site` if blank should count as absent.

REVIEW: FAIL

I reviewed ticket 03 (brightsky-verify, step mapping) over 82d5593e3d4a4c09d89c14f40d331508341e420c..046a1c43a662bd7be0654791b98bab90408b0763. That end commit is HEAD, so there are no later commits I left out. I read the ticket as it stood at the base commit and never saw `## Answer`. The ticket's Status changed from open to resolved. My commands left no files behind.

SPEC
- test_brightsky_mapping.py passes and covers every target kind and each UnmappableStep reason: MET. I ran `python3 -m pytest stepper/tests/unit/test_brightsky_mapping.py -q` and it printed "100 passed". The parametrized `test_target_kinds` covers role+name, text-only, css, xpath, `#id`, and role+name plus a selector. `test_unmappable_steps_name_their_number_and_reason` and the tests next to it cover the reasons.
- Pilot fixture maps to navigate, fill with press_enter, then two clicks, all strict; the role-only textbox fills through `{"css": '[placeholder="Search"]'}` with no role key: MET. The fixture matches `pilot-workflows.ts`. `test_the_pilot_maps_to_navigate_fill_click_click` checks the navigate to `https://openlibrary.org/`, the fill of "The Hobbit" with `press_enter`, the two clicks, and `extra["strict"] is True` on each acting step. `test_a_textbox_without_a_name_fills_through_its_selector_alone` asserts the exact element dict.
- Host guard rejects evil.com, openlibrary.org.evil.com, user@openlibrary.org, openlibrary.org:8080, 127.0.0.1 and openlibrary.org/.., each naming step 1; the ENV and `{{token}}` titles are refused: MET. `test_the_host_guard_refuses_a_navigate_host_off_the_site` lists all six hosts and asserts step_number == 1. `test_the_env_value_is_refused_before_anything_is_returned` and `test_a_template_in_the_title_is_refused` cover the two titles. All passed in the run above.
- url_matches agrees with matchUrl on startsWith, includes, a valid regex and an invalid regex: MET. `test_url_matches_is_brightsky_match_url` has cases for each. I checked them against `url-match.utils.ts`, which falls back to startsWith on a bad regex.
- All existing unit tests still pass: MET. `python3 -m pytest stepper/tests/unit/ -q` printed "1860 passed".
- Acceptance tests for this ticket: not a failure. `plans/brightsky-verify/acceptance/test_accept_mapping.py` gave 30 passed, 7 failed. All 7 fail with `ModuleNotFoundError: No module named 'stepper.brightsky.targets'`, which is ticket 11, explicitly outside this ticket. The verify_cli failures the conductor saw belong to later tickets.
- scope: OK. The only changes are `stepper/brightsky/mapping.py` and `stepper/tests/unit/test_brightsky_mapping.py` (both listed under Touches), plus the ticket file and one bookkeeping line each in `plans/brightsky-verify/map.md` and `plans/brightsky-verify/learnings.md`, which the flow expects with every ticket.
- test first: OK. Commit 3a589c1 adds only the test file, which imports `stepper.brightsky.mapping`. That module did not exist then, so the test fails without the production change; the conductor also saw it fail.

The ticket is already level 3, so there is no level raise.

REVIEW: PASS
