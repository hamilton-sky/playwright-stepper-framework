# Follow-ups: brightsky-verify

What the run left for later: minor findings of passing reviews, the findings a level 2 ticket passed with after 2 review rounds, and Done when checks this host could not pass. Each is a candidate for a cleanup ticket.

## 01-settle-non-current-versions (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/plans/brightsky-verify/map.md: "§ Decisions so far" now has two lines for the same ticket 01 decision, and they don't match. The older line, which was already there at 124eaf1, gives the skip message as `<slug> v<N> skipped: not the current version`. The new line gives `... (v<M>)`, which is what spec.md and test_accept_verify_cli.py expect. Ticket 06 could build the wrong message from the older line. Fix: delete the older line and keep the new one. (pair review)

## 02-brightsky-config-and-models (left for later)

- 1. minor stepper/brightsky/models.py: `_int` in the readers has no upper bound. `QueueItem` and `WorkflowDetail` accept `version` 10**30, which then shows up later as a `ValueError` from `RunReport` instead of a `BrightSkyResponseError` at the boundary. Pass `MAX_VERSION` as a maximum to `_int` for `version` and `currentVersion.version`. (pair review)
- 2. minor stepper/brightsky/models.py: `WorkflowDetail.from_json` accepts an empty `site` and one longer than the backend's 253-character limit (`""` and `"../../etc"` both pass). The spec's host guard later binds navigation to this value. Require a non-empty string of at most 253 characters. (pair review)
- 3. minor stepper/brightsky/models.py: `RunReport.client` is not checked (`client="admin"` goes onto the wire), so the backend would answer with a 400 instead of a `ValueError` here. Check it against the backend's `WORKFLOW_CLIENTS`, or make it a constant rather than a field. (pair review)

## 03-step-mapping (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: `url_matches` runs a stored regex through `re.search` with no limit on time or pattern length. On my machine `^/(a+)+$` against a 27-character path took 2.6 s, and each extra character roughly doubles that. This is an accepted risk in spec.md § Edge cases: the job's timeout-minutes bounds a hang. A length cap on the pattern or the path would make it cheaper, but this is not required here. (pair review)
- 2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: an empty `expectedDomain` on step 1 is still rejected instead of falling back to `site` (round 1 minor 3, unchanged). It fails safe. Use `or detail.site` if a blank value should count as absent. (pair review)
- 3. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: `role` goes into the element cfg as stored, while the action is chosen with `role.lower()`. A role like "Button" picks the right action, but then may match nothing in `get_by_role`. Strict mode means it fails safe. Consider lower-casing the role in the cfg. (pair review)
- 4. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/mapping.py: the host guard only checks against `detail.site`, so a site like `nip.io` or `co.uk` lets through hosts such as `127.0.0.1.nip.io`. spec.md already lists an allow-list of sites as a possible later addition (round 1 minor 2, unchanged). (pair review)

## 04-big-model-chain (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/engine/ai/providers.py: the `ClaudeProvider` docstring still says "Claude Haiku provider (cheapest Claude)", but the model is now a parameter and the same class backs the big-model rung. Change it to "Claude provider; defaults to Haiku (cheapest), model is configurable." (pair review)
- 2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/tests/unit/test_ai_service.py: `test_without_an_anthropic_key_heal_big_raises` only checks for RuntimeError. If the `is_configured` guard regressed, the call would still fail inside the swallowed provider exception and the test would still pass, so it does not prove "no request". The acceptance test does prove it. To fix, stub `anthropic.Anthropic` or `ClaudeProvider.chat` and assert it was never called. (pair review)
- 3. minor /home/claude/hamilton-sky/playwright-stepper-framework/ARCHITECTURE.md and /home/claude/hamilton-sky/playwright-stepper-framework/README.md: both describe the AI chain as "Groq → Gemini → Claude" and leave out the heal_big rung. Add it, or leave it for ticket 12, which wires it in. (pair review)

## 08-scheduled-workflow (left for later)

- 1. minor .github/workflows/brightsky-verify.yml: The bridge token and the AI keys are set in the job-level `env`, so every step can see them, including third-party actions (checkout, setup-python, cache) and the `pip install`, `playwright install` and `download_models.py` steps. A compromised dependency at install time could read the token. The ticket asks for job-level env and ci.yml does the same, so I rate this minor. To fix: put the secrets in step-level `env` on only the "Detect BrightSky secrets" and "Verify the queue" steps. (pair review)
- 2. minor .github/workflows/brightsky-verify.yml: The actions are pinned by tag (`@v4`, `@v5`), not by commit SHA, and checkout leaves its credentials in place. This matches ci.yml, and the token can only read. To harden: pin to SHAs and add `persist-credentials: false` to checkout. (pair review)
- 3. minor .github/workflows/brightsky-verify.yml: The last step calls `python -m stepper brightsky verify --all-unverified`, and that CLI does not exist yet (ticket 07 is not built; `stepper/brightsky/` has only config, mapping and models). The job would fail if the secrets were set today. They are not set yet, so this is a heads-up about ticket order, not a defect in this ticket. (pair review)

## 10-brightsky-client (left for later)

- 1. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`_read_capped`): a cut-off body is only caught when the response sends `Content-Length`. A cut-off body with no length (close-delimited) cannot be caught, and the code does not say so. Add a line saying that limit is intended. (pair review)
- 2. minor /home/claude/hamilton-sky/playwright-stepper-framework/stepper/brightsky/client.py (`TIMEOUT`): the 20 s is still a limit on each read, not on the whole request. Round 2 accepted this once it was written down, and it now is. Add a total deadline only if CI hangs ever show up. (pair review)

## 11-healed-element-to-target (left for later)

- 1. minor stepper/brightsky/targets.py: `"#" + element_id` is only a valid CSS selector for plain ids. Ids such as `:r1:` (React's useId), `1abc` or `user.name` become an invalid selector or one that matches a different element (`#user.name` means id `user` with class `name`), and `map_version` will then pass it on as `css`. The ticket asks for `"#" + id`, so this follows the spec, but the spec is wrong for those ids. Change: emit `#id` only when the id matches `mapping._ID_SELECTOR`, and otherwise emit `[id="…"]`, escaped the same way as placeholder. (pair review)
- 2. minor stepper/brightsky/targets.py: the placeholder escaping handles `"` and `\` but not newlines or other control characters. A raw newline inside a CSS string is invalid, so such a selector would fail at lookup. Change: also escape `\n`, `\r` and `\f` (for example `\a `), or drop the placeholder when it contains them. (pair review)
- 3. minor stepper/brightsky/targets.py: keys in the element cfg that a target cannot express (for example `nth` or `exact`) are dropped without any sign. A heal that needed `nth` to pick one of several matches turns into a proposal whose strict lookup is ambiguous. The ticket does not cover this case. Change: return None or flag it when the element has keys that would be lost, or note it as a follow-up for ticket 06. (pair review)
- 4. minor stepper/tests/unit/test_brightsky_targets.py: `_valid_plan_step_target` checks the grounding twice (`== "current_page"` and then `in GROUNDINGS`); the second check adds nothing. Change: drop the `GROUNDINGS` check. (pair review)
