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
